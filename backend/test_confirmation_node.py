import asyncio

from agents.confirmation_agent.agent import confirmation_node
from agents.orchestrator.state import AgentIntent


async def main():
    state = {
        "query": "Can my landlord deduct money from my security deposit without bills?",
        "session_id": "test-session",
        "scratchpad": [
            {
                "intent": "rights",
                "status": "ok",
                "output": "Based on Indian law regarding Tenant Security Deposit.",
                "metadata": {
                    "citations": [
                        "Model Tenancy Act, 2021, Section 11 and relevant Section 15 provisions"
                    ],
                    "agent": "RightsExplainerAgent",
                    "model": "gpt-4o-mini / BGE-M3",
                },
            }
        ],
        "retry_counts": {},
    }

    print("\n=== TESTING confirmation_node() ===")

    try:
        result = await confirmation_node(state)

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