# sample tesing 
from services.rag.embedder import BGEM3Embedder
from db.qdrant_client import get_qdrant_client
from core.config import get_settings


QUESTIONS = [
    "Can my landlord deduct money from my security deposit without bills?",
    "What are the rules and timelines for POSH workplace harassment reporting?",
    "How long can a PIO take to answer an RTI application?",
    "What rights do I have if I receive a defective product from e-commerce?",
]


from agents.rights_agent.agent import get_rights_agent

def main():
    settings = get_settings()
    agent = get_rights_agent()
    client = agent.qdrant_client
    embedder = agent.embedder

    print("\n" + "=" * 80)
    print("LEXIS RIGHTS AGENT - RETRIEVAL TEST")
    print("=" * 80)

    for question in QUESTIONS:
        print("\n" + "-" * 80)
        print(f"QUESTION: {question}")
        print("-" * 80)

        vector = embedder.embed_query(question)

        results = client.query_points(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            query=vector,
            limit=3,
            with_payload=True,
        )

        points = results.points

        if not points:
            print("NO RESULTS FOUND")
            continue

        for i, point in enumerate(points, 1):
            payload = point.payload or {}

            print(f"\nResult #{i}")
            print(f"Score:              {point.score:.4f}")
            print(f"Topic:              {payload.get('topic')}")
            print(f"Act:                {payload.get('act_name')}")
            print(f"Section:            {payload.get('section')}")
            print(f"Title:              {payload.get('title')}")
            print(f"Verification:       {payload.get('verification_status')}")
            print(f"Authority:          {payload.get('authority')}")
            print(f"Citation:           {payload.get('citation')}")
            print(f"Source URL:         {payload.get('source_url')}")


if __name__ == "__main__":
    main()