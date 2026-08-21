---
name: langgraph_memory
description: Patterns for implementing Letta-style memory blocks in LangGraph.
---

# Letta-Style Memory in LangGraph

This skill describes how to implement a Letta-style core memory block (Persona Block and Human Block) inside a LangGraph state machine.

## Pattern

```python
from typing import TypedDict, Annotated, List, Dict, Any
from langgraph.graph import StateGraph, START, END

# 1. Define the State
class AgentState(TypedDict):
    # Standard conversational history
    messages: Annotated[list, "append"]
    
    # Core Memory Blocks
    persona_block: str
    human_block: str
    
    # Tool call metadata or reasoning scratchpad can also be stored here
    current_task: str

# 2. Define the Memory Injection Node
def inject_memory(state: AgentState):
    """
    Constructs the system prompt by combining the Persona and Human blocks.
    In a real implementation, this could prepend a SystemMessage to the messages list
    or inject it into the prompt template.
    """
    system_prompt = f"""
    You are an AI Employee.
    
    [PERSONA BLOCK]
    {state.get("persona_block", "You are a helpful assistant.")}
    
    [HUMAN BLOCK]
    {state.get("human_block", "No specific human details known.")}
    """
    
    # Example: you might update a system message in the state here, or just return it
    # We will just print for demonstration
    # print("System Prompt Compiled:", system_prompt)
    return {"messages": []} # Return state updates

# 3. Define the LLM Node
def call_model(state: AgentState):
    # Here you would use the nemotron_api to generate the response
    # passing in the state["messages"] alongside the system prompt compiled above.
    pass

# 4. Construct the Graph
workflow = StateGraph(AgentState)
workflow.add_node("inject_memory", inject_memory)
workflow.add_node("call_model", call_model)

workflow.add_edge(START, "inject_memory")
workflow.add_edge("inject_memory", "call_model")
workflow.add_edge("call_model", END)

# In production, use a checkpointer like SqliteSaver
# app = workflow.compile(checkpointer=memory)
```

## Critical Rules
1. The state must explicitly separate short-term `messages` from long-term memory blocks like `persona_block` and `human_block`.
2. Before the reasoning engine (LLM) is invoked, the memory blocks must be compiled into the system prompt.
