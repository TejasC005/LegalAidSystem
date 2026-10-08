# sample file
import asyncio

from agents.rights_agent.agent import get_rights_agent


async def main():
    query = "Can my landlord deduct money from my security deposit without bills?"

    agent = get_rights_agent()

    print("\n" + "=" * 80)
    print("DIRECT RIGHTS AGENT TEST")
    print("=" * 80)

    try:
        result = await agent.explain_rights(query)

        print("\nRESULT TYPE:")
        print(type(result))

        print("\nRESULT:")
        print(result)

        print("\nRESULT LENGTH:")
        print(len(result))

    except Exception as exc:
        print("\nERROR:")
        print(type(exc).__name__)
        print(str(exc))

        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())