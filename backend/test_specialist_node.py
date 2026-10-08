import asyncio

from agents.orchestrator.agent import specialist_node
from agents.orchestrator.state import AgentIntent


async def main():
    state = {
        "query": "Can my landlord deduct money from my security deposit without bills?",
        "session_id": "test-session",
        "scratchpad": [],
        "retry_counts": {},
        "_current_intent": AgentIntent.RIGHTS,
    }

    print("\n=== TESTING specialist_node() ===")

    try:
        result = await specialist_node(state)

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

        raise


if __name__ == "__main__":
    asyncio.run(main())