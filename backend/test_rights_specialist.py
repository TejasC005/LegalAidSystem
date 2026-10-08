import asyncio

from agents.orchestrator.agent import _run_specialist_work
from agents.orchestrator.state import AgentIntent


async def main():
    query = "What are the rules and timelines for POSH workplace harassment reporting?"

    print("\n=== TESTING ORCHESTRATOR RIGHTS SPECIALIST ===")

    result = await _run_specialist_work(
        AgentIntent.RIGHTS,
        query,
        {},
    )

    print("\nRESULT TYPE:")
    print(type(result))

    print("\nRESULT:")
    print(result)

    print("\nRESULT LENGTH:")
    print(len(result))


if __name__ == "__main__":
    asyncio.run(main())
    