#In last one, we added fun in tools life, now LLM can play with multiple tools to execute complex integration.
#But there is cost to call LLM, LLM tells us if it needs to call tool.
#In my case I have many stocks against which when I had to run processing, it called LLM that many times and that too with addded message and response.
#Below, I am trying to work on what information I have & execute it without need to call LLM again and again.
#Also using plain diskcache to even don't call for same input. Was getting must specially while developing the tool.
import os
import json
from diskcache import Cache
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
        self.cache = Cache(".")
        
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
        1. Build a plan, what all you need to call.
        2. If you don not have tool available, mention by adding attribute : "newToolRequired":true
        2. Generate heirarichal response like, here step2 depends on step 1. Step 2 requires to be having new tool creation.
        {{
            "summary": "description of plan",
            "plan": [
            {{
              "step": 1,
              "tool_name": "name",
              "params": {...},
              "dependsOn": "None",
              "expectListResponse" : false,
              "stop_on_error": true
            }},
            {{
              "step": 2,
              "tool_name": "name",
              "params": {...},
              "newToolRequired": true,
              "expectListResponse" : false,
              "dependsOn": "1", 
              "stop_on_error": true
            }}
            ...
            ]
        }}
                
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


    def build_graph(self, plan):
        """
        Transforms a flat list of tasks into a Directed Acyclic Graph (DAG).
        Returns:
            nodes: Dict mapping step_id to task data
            ready_queue: List of step_ids with no dependencies
            waiting_for_counts: Dict tracking how many parents each step is waiting for
        """
        # 1. Map step_id -> Task Object for O(1) lookup
        nodes = {task['step']: task for task in plan}
        
        # 2. Initialize the dependency tracker and notification lists
        waiting_for_counts = {step_id: 0 for step_id in nodes}
        for step_id in nodes:
            nodes[step_id]['next_steps'] = []

        ready_queue = []
        
        # 3. Analyze the dependencies defined by the LLM
        for step_id, task in nodes.items():
            dep = task.get('dependsOn')
            
            # Check if this task is an entry point (no parents)
            if dep is None or str(dep).lower() == 'none':
                ready_queue.append(step_id)
            else:
                try:
                    parent_id = int(dep)
                    if parent_id in nodes:
                        # Link parent to child: Step Parent -> Next: [Step Child]
                        nodes[parent_id]['next_steps'].append(step_id)
                        # Increment the "in-degree" (waiting count)
                        waiting_for_counts[step_id] += 1
                    else:
                        # Fallback: if LLM provides an invalid parent ID, treat as ready
                        ready_queue.append(step_id)
                except ValueError:
                    ready_queue.append(step_id)
                
        return nodes, ready_queue, waiting_for_counts

    def execute_graph_sequentially(self, nodes, queue, waiting_for_counts):
        """
        Executes the plan one tool at a time, respecting dependencies 
        and handling list-based branching (fan-out).
        """
        context = {} # Stores results: {step_id: tool_output}

        print(f"--- Starting Execution: {len(nodes)} steps in plan ---")

        # Process the queue until empty (FIFO)
        while queue:
            current_id = queue.pop(0)
            task = nodes[current_id]
            
            # --- PHASE 1: Dependency & Loop Detection ---
            parent_id = task.get('dependsOn')
            params_template = task['params']
            
            is_parent_list = False
            if parent_id and str(parent_id).lower() != 'none':
                parent_node = nodes.get(int(parent_id))
                # Check if the parent step was explicitly marked as a list producer
                if parent_node and parent_node.get('expectListResponse'):
                    is_parent_list = True

            # --- PHASE 2: Execution ---
            if is_parent_list:
                # FAN-OUT: The parent produced a list, so we run this tool for EACH item
                list_of_items = context.get(int(parent_id), [])
                print(f"Looping Step {current_id} ('{task['tool_name']}') for {len(list_of_items)} items...")
                
                step_results = []
                for item in list_of_items:
                    # Inject the specific item into the parameters
                    single_params = self.inject_value(params_template, item)
                    
                    # Execute the tool for this item
                    res = self.handle_current_response({
                        "action": "call_tool",
                        "tool_name": task['tool_name'],
                        "params": single_params
                    })
                    step_results.append(res)
                
                # Store the collection of results for this step
                context[current_id] = step_results
            else:
                # SINGLE EXECUTION: standard tool call
                print(f"Executing Step {current_id}: {task['tool_name']}")
                
                # Resolve parameters (inject data from parent if applicable)
                parent_data = None
                if parent_id and str(parent_id).lower() != 'none':
                    parent_data = context.get(int(parent_id))
                
                final_params = self.inject_value(params_template, parent_data)
                
                result = self.handle_current_response({
                    "action": "call_tool",
                    "tool_name": task['tool_name'],
                    "params": final_params
                })
                context[current_id] = result

            # --- PHASE 3: Notification (Unlocking Children) ---
            for next_step_id in task['next_steps']:
                waiting_for_counts[next_step_id] -= 1
                
                # If all parents are finished, the child is ready to enter the queue
                if waiting_for_counts[next_step_id] == 0:
                    queue.append(next_step_id)

        print("--- Plan Execution Finished ---")
        return context

    def inject_value(self, params, value):
        """
        Helper to replace placeholders in parameters.
        Can handle both single strings and dictionaries.
        """
        import json
        if value is None:
            return params
            
        # Convert to string to easily replace placeholders like {stock} or {item}
        p_str = json.dumps(params)
        
        # We replace the common placeholder the LLM tends to use
        # You can expand this to check for {stock}, {item}, or {data}
        placeholder = "{stock}" if "{stock}" in p_str else "{item}"
        
        if isinstance(value, (str, int, float)):
            p_str = p_str.replace(placeholder, str(value))
        
        return json.loads(p_str)

    def callAgent(self, user_input) :
        decision = {}
        if user_input in self.cache:
            print("returning from cache")
            decision = self.cache[user_input]
        else :
            print("cache missed")
            messages=[
                {"role": "system", "content": self.build_system_prompt()},
                {"role": "user", "content": user_input}
            ]
            
            response = openai.chat.completions.create(model="gpt-4o-mini", messages=messages,response_format={"type": "json_object"})
            decision = json.loads(response.choices[0].message.content)
            self.cache.set(user_input, decision, expire=36000) # Optional: expires in 10 hour
            
        print(decision)
        plan,start,waiting_for_counts = self.build_graph(decision['plan'])
        print("......................plan graph............")
        print(plan)
        print("......................Start.................")
        print(start)
        
        output=self.execute_graph_sequentially(plan, start, waiting_for_counts)
        print(output)
            
            
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
