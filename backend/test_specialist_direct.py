import asyncio

from agents.orchestrator.agent import specialist_node


async def main():
    state = {
        "_current_intent": "rights",
        "query": "Can my landlord deduct money from my security deposit without bills?",
    }

    print("\n" + "=" * 80)
    print("DIRECT SPECIALIST NODE TEST")
    print("=" * 80)

    try:
        result = await specialist_node(state)

        print("\nRESULT:")
        print(result)

        print("\nRESULT TYPE:")
        print(type(result))

    except Exception as exc:
        print("\nERROR:")
        print(type(exc).__name__)
        print(str(exc))

        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())