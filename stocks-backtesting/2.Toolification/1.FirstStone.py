# verify how tools work & how can LLM call tools???
import os
import json
import openai

client = OpenAI()
def calculate_square_root(number):
    return math.sqrt(float(number))

tools = {
    "calculate_square_root": calculate_square_root
}

def agent(prompt):
    # Step 1: Ask LLM what tool to use (if any)
    tool_prompt = f"""
    You are an intelligent assistant.
    Available tools: {list(tools.keys())}
    If you need to use a tool, respond in JSON like:
    {{"action": "<tool_name>", "input": "<input_value>"}}
    Otherwise, answer directly.

    User question: {prompt}
    """

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=tool_prompt
    )
    message = response.output_text.strip()

    try:
        action = json.loads(message)
        tool_name = action["action"]
        tool_input = action["input"]
        print(f"🤖 Using tool: {tool_name}({tool_input})")
        result = tools[tool_name](tool_input)

        final_response = client.responses.create(
            model="gpt-4.1-mini",
            input=f"The tool returned: {result}. Formulate a natural answer."
        )
        return final_response.output_text
    except Exception:
        # LLM didn't call a tool, just answered
        return message

# Try it
print(agent("What is the square root of 49?"))
