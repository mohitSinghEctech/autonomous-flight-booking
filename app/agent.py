import os
import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from app.models import SearchFlights, BookFlight
from app.tools import search_flights, TOOL_HANDLERS

from openai import AsyncOpenAI
from dotenv import load_dotenv


MAX_ITERATIONS = 5
REQUIRES_APPROVAL = {
    "book_flight",
}

@dataclass
class AgentState:
    messages: list[Any] = field(default_factory=list)
    pending_tool_call: Any | None = None


load_dotenv()

# Search Flight Tool
search_flights_tool = {
    "name": "search_flights",
    "description": ("Search for available flights. "
                    "origin and destination must be IATA airport codes, "
                    "such as DEL for Delhi and DXB for Dubai."
                    ),
    "parameters": SearchFlights.model_json_schema()
}

book_flight_tool = {
    "name": "book_flight",
    "description": (
        "Book a selected flight. "
        "flight_id must be the exact flight_id returned by search_flights. "
        "Do not modify, shorten, or convert the flight_id. "
        "For example, if search_flights returns AI1000, use AI1000."
    ),
    "parameters": BookFlight.model_json_schema(),
}


client = AsyncOpenAI(
    api_key=os.getenv("LLM_API_KEY")
)

def execute_tool(tool_call):
    try: 
        tool_name = tool_call.function.name
        tool_config = TOOL_HANDLERS.get(tool_name)
        
        if tool_config is None:
            return f"Unknown tool: {tool_call.function.name}"
        
        arguments = json.loads(tool_call.function.arguments)
                
        request = tool_config["model"].model_validate(arguments)
        
        result = tool_config["handler"](request)
        
        if isinstance(result, list):
            result = [
                item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                for item in result
            ]
        elif hasattr(result, "model_dump"):
            result = result.model_dump(mode="json")
        
        return json.dumps(result)
        
    except Exception as error:
        return f"Tool execution failed: {error}"
    
    
async def resume_after_approval(state: AgentState):
    tool_call = state.pending_tool_call
    
    result = execute_tool(tool_call)
    state.messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": result
        }
    )
    state.pending_tool_call = None
    print("\n--- MESSAGES AFTER APPROVAL ---")

    for message in state.messages:
        print(message)

    print("--- END MESSAGES ---\n")
    return state

async def run_agent(state: AgentState):
    
    for _ in range(MAX_ITERATIONS):
        response = await client.chat.completions.create(
            model=os.getenv("LLM_MODEL"),
            messages=state.messages,
            tools=[
                {
                    "type": "function",
                    "function": search_flights_tool
                },
                {
                    "type": "function",
                    "function": book_flight_tool
                }
            ]
        )
        assistant_message = response.choices[0].message
        
        state.messages.append(assistant_message)
        
        if not assistant_message.tool_calls:
            print("Final Answer: ")
            print(assistant_message.content)
            return state
        
        for tool_call in assistant_message.tool_calls:
            tool_name = tool_call.function.name
            
            if tool_name in REQUIRES_APPROVAL:
                print("Approval required for: ", tool_name)
                state.pending_tool_call = tool_call
                print("Approval required for:", tool_call.function.name)
                print("Arguments:", tool_call.function.arguments)
                return state
            
            print("Using tool: ", tool_call.function.name)
            tool_content = execute_tool(tool_call)
            
            state.messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_content
            })
                
    else:
        print("Agent could not complete the request within the allowed steps.")
        return state
        
    
    
async def main():
    state = AgentState(
        messages=[
            {
                "role": "user",
                "content": "Book me an economy flight from Delhi to Dubai on October 1, 2026 for 2 people."
            }
        ]
    )
    state = await run_agent(state)
    
    if state.pending_tool_call is None:
        print("\n\n--------Agent completed without requiring approval.--------\n\n")
        return 
    
    print("Agent paused.")
    print("Pending:", state.pending_tool_call.function.name)
    
    # simulate user approval
    state = await resume_after_approval(state)
    
    print("Booking tool executed.")
    # Second phase: continue from the same state
    state = await run_agent(state)
    
    
if __name__ == "__main__":
    asyncio.run(main())