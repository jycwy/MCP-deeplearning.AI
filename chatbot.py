import arxiv
import json
import os
import time
import urllib.parse
from typing import List
from dotenv import load_dotenv
import anthropic

PAPER_DIR = "papers"
def search_papers(topic: str, max_results: int = 5) -> List[str]:
    """
    Search for papers on arXiv based on a topic and store their information.
    
    Args:
        topic: The topic to search for
        max_results: Maximum number of results to retrieve (default: 5)
        
    Returns:
        List of paper IDs found in the search
    """
    
    try:
        # Sanitize and validate inputs
        if not topic or not topic.strip():
            raise ValueError("Topic cannot be empty")
        
        # Clean up the topic string and limit max_results
        topic = topic.strip()
        max_results = min(max_results, 50)  # Limit to reasonable number
        
        # Use arxiv to find the papers 
        client = arxiv.Client()

        # Search for the most relevant articles matching the queried topic
        search = arxiv.Search(
            query = topic,
            max_results = max_results,
            sort_by = arxiv.SortCriterion.Relevance
        )

        # Add retry logic with exponential backoff
        papers = None
        for attempt in range(3):
            try:
                papers = list(client.results(search))
                break
            except Exception as e:
                if attempt < 2:  # Don't sleep on last attempt
                    wait_time = (2 ** attempt) * 2  # 2, 4, 8 seconds
                    print(f"ArXiv API error (attempt {attempt + 1}): {str(e)}. Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    raise Exception(f"Failed to retrieve papers after 3 attempts: {str(e)}")

        if not papers:
            return []

        # Create directory for this topic
        path = os.path.join(PAPER_DIR, topic.lower().replace(" ", "_"))
        os.makedirs(path, exist_ok=True)
        
        file_path = os.path.join(path, "papers_info.json")

        # Try to load existing papers info
        try:
            with open(file_path, "r") as json_file:
                papers_info = json.load(json_file)
        except (FileNotFoundError, json.JSONDecodeError):
            papers_info = {}

        # Process each paper and add to papers_info  
        paper_ids = []
        for paper in papers:
            try:
                paper_ids.append(paper.get_short_id())
                paper_info = {
                    'title': paper.title,
                    'authors': [author.name for author in paper.authors],
                    'summary': paper.summary,
                    'pdf_url': paper.pdf_url,
                    'published': str(paper.published.date())
                }
                papers_info[paper.get_short_id()] = paper_info
            except Exception as e:
                print(f"Error processing paper {paper.get_short_id()}: {str(e)}")
                continue
        
        # Save updated papers_info to json file
        with open(file_path, "w") as json_file:
            json.dump(papers_info, json_file, indent=2)
        
        print(f"Results are saved in: {file_path}")
        
        return paper_ids
        
    except Exception as e:
        error_msg = f"Error searching papers for topic '{topic}': {str(e)}"
        print(error_msg)
        return []

def extract_info(paper_id: str) -> str:
    """
    Search for information about a specific paper across all topic directories.
    
    Args:
        paper_id: The ID of the paper to look for
        
    Returns:
        JSON string with paper information if found, error message if not found
    """
 
    for item in os.listdir(PAPER_DIR):
        item_path = os.path.join(PAPER_DIR, item)
        if os.path.isdir(item_path):
            file_path = os.path.join(item_path, "papers_info.json")
            if os.path.isfile(file_path):
                try:
                    with open(file_path, "r") as json_file:
                        papers_info = json.load(json_file)
                        if paper_id in papers_info:
                            return json.dumps(papers_info[paper_id], indent=2)
                except (FileNotFoundError, json.JSONDecodeError) as e:
                    print(f"Error reading {file_path}: {str(e)}")
                    continue
    
    return f"There's no saved information related to paper {paper_id}."


# Tool schema
tools = [
    {
        "name": "search_papers",
        "description": "Search for papers on arXiv based on a topic and store their information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic to search for"
                }, 
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to retrieve",
                    "default": 5
                }
            },
            "required": ["topic"]
        }
    },
    {
        "name": "extract_info",
        "description": "Search for information about a specific paper across all topic directories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "paper_id": {
                    "type": "string",
                    "description": "The ID of the paper to look for"
                }
            },
            "required": ["paper_id"]
        }
    }
]

# Tool mapping
mapping_tool_function = {
    "search_papers": search_papers,
    "extract_info": extract_info
}

def execute_tool(tool_name, tool_args):
    
    result = mapping_tool_function[tool_name](**tool_args)

    if result is None:
        result = "The operation completed but didn't return any results."
        
    elif isinstance(result, list):
        result = ', '.join(result)
        
    elif isinstance(result, dict):
        # Convert dictionaries to formatted JSON strings
        result = json.dumps(result, indent=2)
    
    else:
        # For any other type, convert using str()
        result = str(result)
    return result


# chatbot code
load_dotenv() 
client = anthropic.Anthropic()

def process_query(query):
    
    messages = [{'role': 'user', 'content': query}]
    
    response = client.messages.create(max_tokens = 2024,
                                  model = 'claude-3-7-sonnet-20250219', 
                                  tools = tools,
                                  messages = messages)
    
    process_query = True
    while process_query:
        assistant_content = []

        for content in response.content:
            if content.type == 'text':
                
                print(content.text)
                assistant_content.append(content)
                
                if len(response.content) == 1:
                    process_query = False
            
            elif content.type == 'tool_use':
                
                assistant_content.append(content)
                messages.append({'role': 'assistant', 'content': assistant_content})
                
                tool_id = content.id
                tool_args = content.input
                tool_name = content.name
                print(f"Calling tool {tool_name} with args {tool_args}")
                
                result = execute_tool(tool_name, tool_args)
                messages.append({"role": "user", 
                                  "content": [
                                      {
                                          "type": "tool_result",
                                          "tool_use_id": tool_id,
                                          "content": result
                                      }
                                  ]
                                })
                response = client.messages.create(max_tokens = 2024,
                                  model = 'claude-3-7-sonnet-20250219', 
                                  tools = tools,
                                  messages = messages) 
                
                if len(response.content) == 1 and response.content[0].type == "text":
                    print(response.content[0].text)
                    process_query = False

# chat loop
def chat_loop():
    print("Type your queries or 'quit' to exit.")
    while True:
        try:
            query = input("\nQuery: ").strip()
            if query.lower() == 'quit':
                break
    
            process_query(query)
            print("\n")
        except Exception as e:
            print(f"\nError: {str(e)}")


chat_loop()