from langchain_core.language_models import BaseChatModel
from langchain_core.vectorstores import VectorStoreRetriever

from backend.research_agent import GraphState, Retriever
from backend.research_agent.generate_chain import create_generate_chain
from backend.research_agent.graph import Steps

from langchain.schema import Document

import logging

logger = logging.getLogger(__name__)


class GraphNodes:
    def __init__(self, llm: BaseChatModel, retriever: Retriever, retrieval_grader, web_search_tool):
        self.llm = llm
        self.retriever = retriever
        self.retrieval_grader = retrieval_grader
        # self.hallucination_grader = hallucination_grader
        # self.code_evaluator = code_evaluator
        # self.question_rewriter = question_rewriter
        self.web_search_tool = web_search_tool
        self.paper_search_tool = None
        self.generate_chain = create_generate_chain(llm)

    def vector_store_retrieve(self, state):
        """
        Retrieve documents

        Args:
            state (dict): The current graph state

        Returns:
            state (dict): New key added to state, documents, that contains retrieved documents
        """
        print("---RETRIEVE---")
        prompt = state["prompt"]

        # Retrieval
        documents = self.retriever.sim_search(prompt)
        state["resources"] = documents
        state["steps"] = [Steps.VECTOR_STORE_RETRIEVAL.value]
        return state

    def generate(self, state):
        """
        Generate answer

        Args:
            state (dict): The current graph state

        Returns:
            state (dict): New key added to state, generation, that contains LLM generation
        """
        print("---GENERATE---")
        prompt = state["prompt"]
        documents = state["resources"]

        # RAG generation
        generation = self.generate_chain.invoke({"documents": '\n'.join(f"{index + 1}. {item}" for index, item in enumerate(documents)), "prompt": prompt})
        state["generation"] = generation
        state["steps"].append(Steps.LLM_GENERATION.value)
        return state

    def _base_grade_documents(self, state: GraphState, previous_state: str):
        prompt = state["prompt"]
        resources = state["resources"]
        state["steps"].append(f"{previous_state}_grade_docs")

        filtered_resources = []
        next_search = False

        for resource in resources:
            score = self.retrieval_grader.invoke({
                "prompt": prompt, "resources": resource
            })
            if score["score"].lower() == "yes":
                filtered_resources.append(resource)
            else:
                next_search = True
                continue

        if next_search:
            match previous_state:
                case "vector_store":
                    state["paper_search_performed"] = True
                    state["steps"].append(Steps.VECTOR_STORE_EVALUATION.value)
                case "paper_search":
                    state["web_search_performed"] = True
                    state["steps"].append(Steps.PAPER_SEARCH_EVALUATION.value)
        state["resources"] = filtered_resources
        return state

    def grade_vector_store_documents(self, state: GraphState):
        print("---GRADE VECTOR STORE DOCUMENTS---")
        return self._base_grade_documents(state, "vector_store")

    def grade_paper_search_documents(self, state: GraphState):
        return self._base_grade_documents(state, "paper_search")

    def web_search(self, state: GraphState):
        prompt = state["prompt"]
        web_results = self.web_search_tool.invoke({"query": prompt})
        state["resources"] = [
            Document(page_content=result["content"], metadata={"url": result["url"]}) for result in web_results
        ]
        state["steps"].append(Steps.WEB_SEARCH_RETRIEVAL)
        return state

    def paper_search(self, state: GraphState):
        ...

    def grade_documents(self, state):
        """
        Determines whether the retrieved documents are relevant to the question.

        Args:
            state (dict): The current graph state

        Returns:
            state (dict): Updates documents key with only filtered relevant documents
        """
        print("---CHECK DOCUMENT RELEVANCE TO PROMPT---")
        prompt = state["prompt"]
        resources = state["resources"]

        # score each doc
        filtered_docs = []

        for d in documents:
            score = self.retrieval_grader.invoke({"input": prompt, "document": d.page_content})
            grade = score["score"]
            if grade == "yes":
                print("---GRADE: DOCUMENT RELEVANT---")
                filtered_docs.append(d)
            else:
                print("---GRADE: DOCUMENT IR-RELEVANT---")
                continue

        return {"documents": filtered_docs, "input": prompt}

    def transform_query(self, state):
        """
        Transform the query to produce a better question.

        Args:
            state (dict): The current graph state

        Returns:
            state (dict): Updates question key with a re-phrased question
        """
        print("---TRANSFORM QUERY---")
        question = state["input"]
        documents = state["documents"]

        # Re-write question
        better_question = self.question_rewriter.invoke({"input": question})
        return {"documents": documents, "input": better_question}