# I had many stocks to scan. All was working great for simple prompt.
# I thought why not to add a prompt where my agent can get all stocks (a tool to return all stocks) and then call another tool for all like: 
# for all stocks : {stock} (from get all stocks), run calculate metrics {stock}
# Here the earlier program keep showing the list, but could not complete end to end task. So, following was done to help it out.

import os
import json
import importlib.util
from java_tools import JavaToolsAgent
# Note: Ensure you have an OpenAI key in your environment variables
import openai

class Orchestrator:
    def __init__(self):
        self.java_worker = JavaToolsAgent()
        self.tools = self.java_worker.get_tool_list();
        self.tools_dir = "tools"
        self.registry_path = os.path.join(self.tools_dir, "registry.json")
        self.history = []
        
        # Ensure tools directory exists
        if not os.path.exists(self.tools_dir):
            os.makedirs(self.tools_dir)

    def load_dynamic_registry(self):
        """Reads the registry.json to see what new tools have been invented."""
        if os.path.exists(self.registry_path):
            with open(self.registry_path, "r") as f:
                return json.load(f)
        return {}

    def build_system_prompt(self):
        """Constructs the prompt with the latest list of tools from the Java Agent."""
        
        # 1. Pull the real tools from your java_agent instance
        # Assuming self.java_agent is your instance of TradingAgent
        
        java_tools = self.java_worker.get_tools_metadata()
        
        # 2. Format them for the prompt
        tool_descriptions = []
        for name, desc in java_tools.items():
            tool_descriptions.append(f"- {name}: {desc}")

        # 3. Join them into the prompt string
        return f"""
        You are the Manager of a Trading System. Your goal is to fulfill user requests using available tools.
        
        CURRENT TOOLS:
        {chr(10).join(tool_descriptions)}
        
        DECISION RULES:
        1. If a tool exists for the request & this is not only task required, return JSON: {{"all_task_completed": false,"action": "call_tool", "tool_name": "name", "params": {{...}}}}
        1.a. If a tool exists for the request & this is the only task required, return JSON: {{"all_task_completed": true,"action": "call_tool", "tool_name": "name", "params": {{...}}}}
        2. If NO tool exists & this is not only task required, return JSON: {{"all_task_completed": false,"action": "suggest_new_tool", "requirement": "description of what is needed"}}
        2.a. If NO tool exists & this is the only task required, return JSON: {{"all_task_completed": true,"action": "suggest_new_tool", "requirement": "description of what is needed"}}
        3. SEQUENTIAL TASKS: If a request requires multiple steps (e.g., 'for all stocks...'), 
           start with the first tool. Once you receive the results, provide the next 
           set of tool calls one by one.
        4. OBSERVATION: When tool results are provided, use them to decide your next 'action'.
        5. In case of final task, set attribute "all_task_completed":true
        6. In case all work completed and no tool to be executed return JSON: {{"all_task_completed": false,"action": "no_tool_call_required"}}
        
        Output ONLY valid JSON.
        """
    
    def call_llm(self, user_query):
        """Asks the LLM to decide on an action."""
        response = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": self.build_system_prompt()},
                {"role": "user", "content": user_query}
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    
  
    def run_dynamic_tool(self, tool_name, params):
        """Dynamically imports and executes a generated tool."""
        file_path = os.path.join(self.tools_dir, f"{tool_name}.py")
        spec = importlib.util.spec_from_file_location(tool_name, file_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.run(params) # All new tools must have a run() function

    def start(self):
        print("--- Trading Orchestrator Online ---")
        while True:
            user_input = input("\nYou: ")
            if user_input.lower() in ['exit', 'quit']: break
            
            self.callAgent(user_input)

    def callAgent(self, user_input) :
        messages=[
            {"role": "system", "content": self.build_system_prompt()},
            {"role": "user", "content": user_input}
        ]
        
        response = openai.chat.completions.create(model="gpt-4o-mini", messages=messages,response_format={"type": "json_object"})
        decision = json.loads(response.choices[0].message.content)
            
        print(decision)

        if not decision["all_task_completed"] :
            while not decision["all_task_completed"] :
                result = self.handle_current_response(decision)
                print(result)
                messages.append({"role": "assistant", "content": json.dumps(decision)})
                messages.append({"role": "user", "content": f"Tool Result: {json.dumps(result)}"})
                response = openai.chat.completions.create(model="gpt-4o-mini", messages=messages,response_format={"type": "json_object"})
                decision = json.loads(response.choices[0].message.content)
                print(decision)
        result = self.handle_current_response(decision)
        print(result)
            
            
    def handle_current_response(self, decision) :
        action = decision["action"]
        if action is None or action == "no_tool_call_required" :
            return "No tool to call for this request"
        elif decision["action"] == "call_tool":
            name = decision["tool_name"]
            print ("About to call " + name + " with params: " + str(decision['params']))
        
            result = self.tools[name](decision['params'])
            
            #print(f"Agent: {result}")
            return result
            
        elif decision["action"] == "suggest_new_tool":
            print(f"Agent: I don't have a tool for that yet. I need to build: {decision['requirement']}")
            confirm = input("Should I trigger the Tool Creator? (y/n): ")
            if confirm.lower() == 'y':
                # This is where we will call ToolCreatorAgent later
                print("Status: Handing off to Tool Creator...")
                # self.dev_worker.create_tool(decision['requirement'])
                return "done"
            else :
                return "User refused to create new tool"
            
if __name__ == "__main__":
    orchestrator = Orchestrator()
    orchestrator.start()
