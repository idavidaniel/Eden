---
name: nemotron_api
description: Instructions for invoking the NVIDIA Nemotron API and extracting reasoning streams.
---

# NVIDIA Nemotron API Skill

This skill provides the standard implementation pattern for connecting to the NVIDIA Nemotron 3.5 Lightning API, ensuring that you properly utilize the OpenAI client, configure the `extra_body` parameters for thinking, and correctly extract both reasoning and response streams.

## Pattern

```python
import os
from openai import OpenAI

def generate_with_reasoning(prompt: str):
    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=os.getenv("NVIDIA_API_KEY")
    )

    completion = client.chat.completions.create(
        model="nvidia/nemotron-3.5-lightning-30b-a3b",
        messages=[{"role": "user", "content": prompt}],
        temperature=1,
        top_p=0.95,
        max_tokens=16384,
        extra_body={
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": 16384
        },
        stream=True
    )

    reasoning_text = ""
    content_text = ""

    for chunk in completion:
        if not chunk.choices:
            continue
        
        # Extract reasoning content
        reasoning = getattr(chunk.choices[0].delta, "reasoning_content", None)
        if reasoning:
            reasoning_text += reasoning
            print(reasoning, end="", flush=True)
            
        # Extract actual content
        content = chunk.choices[0].delta.content
        if content:
            content_text += content
            print(content, end="", flush=True)
            
    return reasoning_text, content_text
```

## Critical Rules
1. Always include `extra_body={"chat_template_kwargs":{"enable_thinking":True},"reasoning_budget":16384}` to enable reasoning.
2. The reasoning stream is exposed via `getattr(chunk.choices[0].delta, "reasoning_content", None)`. It is not part of the standard `content` field.
3. The model supports up to 16,384 tokens.
