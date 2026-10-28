import asyncio

from agents.orchestrator.agent import orchestrator_graph


async def main():
    query = "Can my landlord deduct money from my security deposit without bills?"

    print("\n=== TESTING FULL ORCHESTRATOR GRAPH ===")
    print("Query:", query)

    try:
        result = await orchestrator_graph.ainvoke(
            {
                "query": query,
                "session_id": "test-full-orchestrator",
                "conversation_history": [],
                "intents": [],
                "confidence": 0.0,
                "scratchpad": [],
                "final_response": "",
                "status": "pending",
                "llm_calls_used": 0,
                "llm_calls_limit": 10,
                "retry_target": None,
                "retry_counts": {},
                "retry_feedback": "",
                "contradiction_note": None,
                "confirmed_outputs": [],
            }
        )

        print("\nSUCCESS")
        print("RESULT TYPE:")
        print(type(result))

        print("\nRESULT:")
        print(result)

    except Exception as e:
        print("\nFAILED")
        print("EXCEPTION TYPE:")
        print(type(e))

        print("\nEXCEPTION:")
        print(repr(e))

        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())