# Agentic Test Results

## Query: How are you?

### Planner Request

```json
{
  "messages": [
    {
      "role": "system",
      "content": "# Planner Service System Prompt\n\nYou are the planner service for a Salesforce Q&A chatbot. Your role is to analyze user requests and orchestrate the appropriate combination of agents and tools to provide comprehensive answers.\n\n## Your Capabilities\n- Analyze user intent and determine required actions\n- Route requests to appropriate specialized agents (SQL, Graph)\n- Coordinate multi-step workflows\n- Combine results from multiple agents\n- Provide direct answers for general questions\n\n## Agent Routing Guidelines\n\n### SQL Agent\nRoute to SQL agent for:\n- Data analysis and reporting requests\n- Questions about account performance, sales metrics\n- Requests for specific data queries or reports\n- Trend analysis and statistical questions\n\n### Graph Agent  \nRoute to Graph agent for:\n- Relationship and connection questions\n- Account hierarchy and organizational structure\n- Partnership and collaboration inquiries\n- Network analysis and pattern discovery\n\n### Direct Response\nProvide direct answers for:\n- General knowledge questions not related to proprietary data.\n\n### Multiple Function selection\n- You may select 1 or more tools to call - depending on User question.\n- If user asks about sales data AND relationships, you can call both tools.\n\n\n## Account Extraction Requirement\nFor every agent/tool call (e.g., SQL or Graph agent), you MUST extract the list of account names or aliases explicitly mentioned in the user query. Add these as an array field `accounts_mentioned` (list of strings, or `null` if no accounts are mentioned) in the agent/tool call parameters. If the user query is generic (e.g., \"sum of sales across all accounts\"), set `accounts_mentioned` to `null`.\n\n## Planning Process\n1. **Analyze Request**: Understand user intent and required information\n2. **Determine Agents**: Select appropriate agents based on request type\n3. **Extract Accounts**: Identify and list all account names/aliases mentioned in the query (or set to `null` if none)\n4. **Plan Sequence**: Order agent calls for optimal workflow\n5. **Coordinate Execution**: Manage agent interactions and data flow\n6. **Synthesize Results**: Combine outputs into coherent response\n\n## Multi-Agent Workflows\nFor complex requests that need multiple agents:\n1. Start with broader context (Graph agent for relationships)\n2. Drill down to specific data (SQL agent for metrics)\n3. Combine insights from both perspectives\n4. Provide unified, actionable recommendations\n\n## Response Quality\n- Ensure responses are complete and accurate\n- Maintain conversation context across agent calls\n- Provide clear explanations of methodology\n- Suggest follow-up questions and actions\n\nRemember: Your goal is to provide the most comprehensive and useful response by intelligently orchestrating available agents and tools.\n"
    },
    {
      "role": "user",
      "content": "How are you?"
    }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "graph_agent",
        "description": "Graph agent for querying relationships, connections, and account information from the knowledge graph",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string"
            },
            "accounts_mentioned": {
              "type": [
                "array",
                "null"
              ],
              "items": {
                "type": "string"
              }
            }
          },
          "required": [
            "query",
            "accounts_mentioned"
          ]
        }
      }
    },
    {
      "type": "function",
      "function": {
        "name": "sql_agent",
        "description": "SQL agent for querying sales data, revenue metrics, and business analytics from the Fabric Lakehouse",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string"
            },
            "accounts_mentioned": {
              "type": [
                "array",
                "null"
              ],
              "items": {
                "type": "string"
              }
            }
          },
          "required": [
            "query",
            "accounts_mentioned"
          ]
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

### Planner Raw Response

```json
{
  "id": "chatcmpl-CIwRyro7d0RsL0TCHsakCYZjoiP6Y",
  "choices": [
    {
      "finish_reason": "stop",
      "index": 0,
      "logprobs": null,
      "message": {
        "content": "I'm doing well, thank you! How can I assist you with your Salesforce data or account questions today?",
        "refusal": null,
        "role": "assistant",
        "annotations": [],
        "audio": null,
        "function_call": null,
        "tool_calls": null
      },
      "content_filter_results": {
        "hate": {
          "filtered": false,
          "severity": "safe"
        },
        "self_harm": {
          "filtered": false,
          "severity": "safe"
        },
        "sexual": {
          "filtered": false,
          "severity": "safe"
        },
        "violence": {
          "filtered": false,
          "severity": "safe"
        }
      }
    }
  ],
  "created": 1758630622,
  "model": "gpt-4.1-2025-04-14",
  "object": "chat.completion",
  "service_tier": null,
  "system_fingerprint": "fp_9ab7d013ff",
  "usage": {
    "completion_tokens": 23,
    "prompt_tokens": 648,
    "total_tokens": 671,
    "completion_tokens_details": {
      "accepted_prediction_tokens": 0,
      "audio_tokens": 0,
      "reasoning_tokens": 0,
      "rejected_prediction_tokens": 0
    },
    "prompt_tokens_details": {
      "audio_tokens": 0,
      "cached_tokens": 0
    }
  },
  "prompt_filter_results": [
    {
      "prompt_index": 0,
      "content_filter_results": {
        "hate": {
          "filtered": false,
          "severity": "safe"
        },
        "self_harm": {
          "filtered": false,
          "severity": "safe"
        },
        "sexual": {
          "filtered": false,
          "severity": "safe"
        },
        "violence": {
          "filtered": false,
          "severity": "safe"
        }
      }
    }
  ]
}
```

### Planner Assistant Answer

I'm doing well, thank you! How can I assist you with your Salesforce data or account questions today?

---

## Query: All sales for Microsoft and its account relationships

### Planner Request

```json
{
  "messages": [
    {
      "role": "system",
      "content": "# Planner Service System Prompt\n\nYou are the planner service for a Salesforce Q&A chatbot. Your role is to analyze user requests and orchestrate the appropriate combination of agents and tools to provide comprehensive answers.\n\n## Your Capabilities\n- Analyze user intent and determine required actions\n- Route requests to appropriate specialized agents (SQL, Graph)\n- Coordinate multi-step workflows\n- Combine results from multiple agents\n- Provide direct answers for general questions\n\n## Agent Routing Guidelines\n\n### SQL Agent\nRoute to SQL agent for:\n- Data analysis and reporting requests\n- Questions about account performance, sales metrics\n- Requests for specific data queries or reports\n- Trend analysis and statistical questions\n\n### Graph Agent  \nRoute to Graph agent for:\n- Relationship and connection questions\n- Account hierarchy and organizational structure\n- Partnership and collaboration inquiries\n- Network analysis and pattern discovery\n\n### Direct Response\nProvide direct answers for:\n- General knowledge questions not related to proprietary data.\n\n### Multiple Function selection\n- You may select 1 or more tools to call - depending on User question.\n- If user asks about sales data AND relationships, you can call both tools.\n\n\n## Account Extraction Requirement\nFor every agent/tool call (e.g., SQL or Graph agent), you MUST extract the list of account names or aliases explicitly mentioned in the user query. Add these as an array field `accounts_mentioned` (list of strings, or `null` if no accounts are mentioned) in the agent/tool call parameters. If the user query is generic (e.g., \"sum of sales across all accounts\"), set `accounts_mentioned` to `null`.\n\n## Planning Process\n1. **Analyze Request**: Understand user intent and required information\n2. **Determine Agents**: Select appropriate agents based on request type\n3. **Extract Accounts**: Identify and list all account names/aliases mentioned in the query (or set to `null` if none)\n4. **Plan Sequence**: Order agent calls for optimal workflow\n5. **Coordinate Execution**: Manage agent interactions and data flow\n6. **Synthesize Results**: Combine outputs into coherent response\n\n## Multi-Agent Workflows\nFor complex requests that need multiple agents:\n1. Start with broader context (Graph agent for relationships)\n2. Drill down to specific data (SQL agent for metrics)\n3. Combine insights from both perspectives\n4. Provide unified, actionable recommendations\n\n## Response Quality\n- Ensure responses are complete and accurate\n- Maintain conversation context across agent calls\n- Provide clear explanations of methodology\n- Suggest follow-up questions and actions\n\nRemember: Your goal is to provide the most comprehensive and useful response by intelligently orchestrating available agents and tools.\n"
    },
    {
      "role": "user",
      "content": "All sales for Microsoft and its account relationships"
    }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "graph_agent",
        "description": "Graph agent for querying relationships, connections, and account information from the knowledge graph",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string"
            },
            "accounts_mentioned": {
              "type": [
                "array",
                "null"
              ],
              "items": {
                "type": "string"
              }
            }
          },
          "required": [
            "query",
            "accounts_mentioned"
          ]
        }
      }
    },
    {
      "type": "function",
      "function": {
        "name": "sql_agent",
        "description": "SQL agent for querying sales data, revenue metrics, and business analytics from the Fabric Lakehouse",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string"
            },
            "accounts_mentioned": {
              "type": [
                "array",
                "null"
              ],
              "items": {
                "type": "string"
              }
            }
          },
          "required": [
            "query",
            "accounts_mentioned"
          ]
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

### Planner Raw Response

```json
{
  "id": "chatcmpl-CIwRzubrSN6E56rNmWWODEv6ZjxOW",
  "choices": [
    {
      "finish_reason": "tool_calls",
      "index": 0,
      "logprobs": null,
      "message": {
        "content": null,
        "refusal": null,
        "role": "assistant",
        "annotations": [],
        "audio": null,
        "function_call": null,
        "tool_calls": [
          {
            "id": "call_s3Wa7rq704ocuiDm4edi6bFy",
            "function": {
              "arguments": "{\"query\": \"Retrieve all sales data for Microsoft and its related accounts.\", \"accounts_mentioned\": [\"Microsoft\"]}",
              "name": "sql_agent"
            },
            "type": "function"
          },
          {
            "id": "call_uDCPmz8aafpOWp2CbjxSJMz4",
            "function": {
              "arguments": "{\"query\": \"Show all account relationships for Microsoft.\", \"accounts_mentioned\": [\"Microsoft\"]}",
              "name": "graph_agent"
            },
            "type": "function"
          }
        ]
      },
      "content_filter_results": {}
    }
  ],
  "created": 1758630623,
  "model": "gpt-4.1-2025-04-14",
  "object": "chat.completion",
  "service_tier": null,
  "system_fingerprint": "fp_9ab7d013ff",
  "usage": {
    "completion_tokens": 73,
    "prompt_tokens": 652,
    "total_tokens": 725,
    "completion_tokens_details": {
      "accepted_prediction_tokens": 0,
      "audio_tokens": 0,
      "reasoning_tokens": 0,
      "rejected_prediction_tokens": 0
    },
    "prompt_tokens_details": {
      "audio_tokens": 0,
      "cached_tokens": 0
    }
  },
  "prompt_filter_results": [
    {
      "prompt_index": 0,
      "content_filter_results": {
        "hate": {
          "filtered": false,
          "severity": "safe"
        },
        "self_harm": {
          "filtered": false,
          "severity": "safe"
        },
        "sexual": {
          "filtered": false,
          "severity": "safe"
        },
        "violence": {
          "filtered": false,
          "severity": "safe"
        }
      }
    }
  ]
}
```

### Planner Tool Calls

- Tool Call → sql_agent

  Arguments: {"query": "Retrieve all sales data for Microsoft and its related accounts.", "accounts_mentioned": ["Microsoft"]}


- Tool Call → graph_agent

  Arguments: {"query": "Show all account relationships for Microsoft.", "accounts_mentioned": ["Microsoft"]}


### Agent Request

```json
{
  "messages": [
    {
      "role": "system",
      "content": "# SQL Agent System Prompt\n\nYou are a specialized SQL agent for a Salesforce Q&A chatbot. Your role is to help users query and analyze Salesforce data using SQL.\n\n## Your Capabilities\n- Execute SQL queries against Salesforce data\n- Analyze account performance, sales data, and customer information\n- Generate reports and insights from Salesforce data\n- Help users understand data relationships and trends\n\n## Guidelines\n1. **Always validate user permissions** before executing queries\n2. **Use parameterized queries** to prevent SQL injection\n3. **Limit result sets** to reasonable sizes (default: 100 rows)\n4. **Explain your findings** in business-friendly language\n5. **Suggest follow-up questions** when appropriate\n\n## Query Types You Handle\n- Account performance analysis\n- Sales pipeline reports\n- Customer segmentation queries\n- Opportunity tracking\n- Activity and engagement metrics\n\n## Response Format\nWhen executing SQL queries:\n1. Validate the request and user permissions\n2. Execute the appropriate SQL query\n3. Format results in a clear, readable format\n4. Provide business insights and explanations\n5. Suggest related queries or follow-up actions\n\n## Error Handling\n- If a query fails, explain the issue in user-friendly terms\n- Suggest alternative approaches or corrections\n- Never expose sensitive system information\n\nRemember: Your goal is to make Salesforce data accessible and actionable for business users.\n"
    },
    {
      "role": "user",
      "content": "Retrieve all sales data for Microsoft and its related accounts."
    }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "graph_agent_function",
        "description": "Query the knowledge graph to find relationships between accounts, contacts, and business entities",
        "parameters": {
          "type": "object",
          "properties": {
            "account_name": {
              "type": "string",
              "description": "Name of the account to search for"
            },
            "relationship_type": {
              "type": "string",
              "description": "Type of relationship to explore (e.g., 'partner', 'competitor', 'supplier')",
              "enum": [
                "partner",
                "competitor",
                "supplier",
                "customer",
                "vendor"
              ]
            },
            "max_depth": {
              "type": "integer",
              "description": "Maximum traversal depth in the graph",
              "default": 2,
              "maximum": 5
            }
          },
          "required": [
            "account_name"
          ]
        }
      }
    },
    {
      "type": "function",
      "function": {
        "name": "sql_query_function",
        "description": "Execute SQL queries against the Fabric Lakehouse to retrieve sales and account data",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string",
              "description": "The SQL query to execute"
            },
            "limit": {
              "type": "integer",
              "description": "Maximum number of rows to return",
              "default": 100
            }
          },
          "required": [
            "query"
          ]
        }
      }
    },
    {
      "type": "function",
      "function": {
        "name": "sql_agent",
        "description": "SQL agent for querying sales data, revenue metrics, and business analytics from the Fabric Lakehouse",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string",
              "description": "User's natural language query about sales data or business metrics"
            },
            "accounts_mentioned": {
              "type": [
                "array",
                "null"
              ],
              "items": {
                "type": "string"
              },
              "description": "List of account names/aliases mentioned in the query, or null if none."
            }
          },
          "required": [
            "query"
          ]
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

### Agent Raw Response

```json
{
  "id": "chatcmpl-CIwS08mjG4ygRTijo6qFiHQwdnuem",
  "choices": [
    {
      "finish_reason": "tool_calls",
      "index": 0,
      "logprobs": null,
      "message": {
        "content": null,
        "refusal": null,
        "role": "assistant",
        "annotations": [],
        "audio": null,
        "function_call": null,
        "tool_calls": [
          {
            "id": "call_Z5qKv2ZHWtEu38ImH3P75neh",
            "function": {
              "arguments": "{\"account_name\":\"Microsoft\",\"relationship_type\":\"partner\",\"max_depth\":2}",
              "name": "graph_agent_function"
            },
            "type": "function"
          }
        ]
      },
      "content_filter_results": {}
    }
  ],
  "created": 1758630624,
  "model": "gpt-4.1-2025-04-14",
  "object": "chat.completion",
  "service_tier": null,
  "system_fingerprint": "fp_c79ab13e31",
  "usage": {
    "completion_tokens": 27,
    "prompt_tokens": 579,
    "total_tokens": 606,
    "completion_tokens_details": {
      "accepted_prediction_tokens": 0,
      "audio_tokens": 0,
      "reasoning_tokens": 0,
      "rejected_prediction_tokens": 0
    },
    "prompt_tokens_details": {
      "audio_tokens": 0,
      "cached_tokens": 0
    }
  },
  "prompt_filter_results": [
    {
      "prompt_index": 0,
      "content_filter_results": {
        "hate": {
          "filtered": false,
          "severity": "safe"
        },
        "self_harm": {
          "filtered": false,
          "severity": "safe"
        },
        "sexual": {
          "filtered": false,
          "severity": "safe"
        },
        "violence": {
          "filtered": false,
          "severity": "safe"
        }
      }
    }
  ]
}
```

### Agent Tool Calls (not executed)

- Tool Call → graph_agent_function

  Arguments: {"account_name":"Microsoft","relationship_type":"partner","max_depth":2}


### Agent Request

```json
{
  "messages": [
    {
      "role": "system",
      "content": "# Graph Agent System Prompt\n\nYou are a specialized graph relationship agent for a Salesforce Q&A chatbot. Your role is to help users understand and navigate complex relationships between accounts, contacts, opportunities, and other Salesforce entities using Gremlin Graph API commands.\n\n## Your Capabilities\n- Query and traverse account relationship graphs\n- Identify connected entities and relationship patterns\n- Analyze account hierarchies and organizational structures\n- Find related accounts through various connection types\n- Provide relationship insights and recommendations\n\n## Guidelines\n1. **Respect user permissions** and only show accessible data\n2. **Explain relationships clearly** using business terminology\n3. **Visualize connections** when helpful\n4. **Consider relationship strength** and relevance\n5. **Suggest relationship-based opportunities**\n\n## Relationship Types You Handle\n- Account hierarchies (parent/child companies)\n- Partnership and vendor relationships\n- Contact connections across accounts\n- Opportunity collaborations\n- Geographic and industry clusters\n- Competitive relationships\n\n## Query Capabilities\n- Find all related accounts within N degrees of separation\n- Identify key relationship paths between entities\n- Discover hidden connections and patterns\n- Analyze relationship strength and frequency\n- Map organizational structures and hierarchies\n\n## Response Format\nWhen analyzing relationships:\n1. Validate the request and user permissions\n2. Execute the appropriate graph traversal\n3. Present relationships in a logical hierarchy\n4. Explain the significance of connections\n5. Suggest actionable insights based on relationships\n\n## Visualization\n- Use clear relationship maps when appropriate\n- Highlight key connections and paths\n- Show relationship types and strengths\n- Group related entities logically\n\n## Error Handling\n- If no relationships found, suggest broadening the search\n- Explain relationship access limitations clearly\n- Provide alternative relationship queries\n\nRemember: Your goal is to reveal valuable business relationships and connection opportunities within Salesforce data.\n"
    },
    {
      "role": "user",
      "content": "Show all account relationships for Microsoft."
    }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "graph_agent_function",
        "description": "Query the knowledge graph to find relationships between accounts, contacts, and business entities",
        "parameters": {
          "type": "object",
          "properties": {
            "account_name": {
              "type": "string",
              "description": "Name of the account to search for"
            },
            "relationship_type": {
              "type": "string",
              "description": "Type of relationship to explore (e.g., 'partner', 'competitor', 'supplier')",
              "enum": [
                "partner",
                "competitor",
                "supplier",
                "customer",
                "vendor"
              ]
            },
            "max_depth": {
              "type": "integer",
              "description": "Maximum traversal depth in the graph",
              "default": 2,
              "maximum": 5
            }
          },
          "required": [
            "account_name"
          ]
        }
      }
    },
    {
      "type": "function",
      "function": {
        "name": "sql_query_function",
        "description": "Execute SQL queries against the Fabric Lakehouse to retrieve sales and account data",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string",
              "description": "The SQL query to execute"
            },
            "limit": {
              "type": "integer",
              "description": "Maximum number of rows to return",
              "default": 100
            }
          },
          "required": [
            "query"
          ]
        }
      }
    },
    {
      "type": "function",
      "function": {
        "name": "graph_agent",
        "description": "Graph agent for querying relationships, connections, and account information from the knowledge graph",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string",
              "description": "User's natural language query about relationships, connections, or account information"
            },
            "accounts_mentioned": {
              "type": [
                "array",
                "null"
              ],
              "items": {
                "type": "string"
              },
              "description": "List of account names/aliases mentioned in the query, or null if none."
            }
          },
          "required": [
            "query"
          ]
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

### Agent Raw Response

```json
{
  "id": "chatcmpl-CIwS1qK2DofoOeNp9guJ92fHSTvhy",
  "choices": [
    {
      "finish_reason": "tool_calls",
      "index": 0,
      "logprobs": null,
      "message": {
        "content": null,
        "refusal": null,
        "role": "assistant",
        "annotations": [],
        "audio": null,
        "function_call": null,
        "tool_calls": [
          {
            "id": "call_LgPLPzjdaVr9XIkC0ppi0DHv",
            "function": {
              "arguments": "{\"account_name\":\"Microsoft\"}",
              "name": "graph_agent_function"
            },
            "type": "function"
          }
        ]
      },
      "content_filter_results": {}
    }
  ],
  "created": 1758630625,
  "model": "gpt-4.1-2025-04-14",
  "object": "chat.completion",
  "service_tier": null,
  "system_fingerprint": "fp_c79ab13e31",
  "usage": {
    "completion_tokens": 17,
    "prompt_tokens": 665,
    "total_tokens": 682,
    "completion_tokens_details": {
      "accepted_prediction_tokens": 0,
      "audio_tokens": 0,
      "reasoning_tokens": 0,
      "rejected_prediction_tokens": 0
    },
    "prompt_tokens_details": {
      "audio_tokens": 0,
      "cached_tokens": 0
    }
  },
  "prompt_filter_results": [
    {
      "prompt_index": 0,
      "content_filter_results": {
        "hate": {
          "filtered": false,
          "severity": "safe"
        },
        "self_harm": {
          "filtered": false,
          "severity": "safe"
        },
        "sexual": {
          "filtered": false,
          "severity": "safe"
        },
        "violence": {
          "filtered": false,
          "severity": "safe"
        }
      }
    }
  ]
}
```

### Agent Tool Calls (not executed)

- Tool Call → graph_agent_function

  Arguments: {"account_name":"Microsoft"}


---

## Query: All sales

### Planner Request

```json
{
  "messages": [
    {
      "role": "system",
      "content": "# Planner Service System Prompt\n\nYou are the planner service for a Salesforce Q&A chatbot. Your role is to analyze user requests and orchestrate the appropriate combination of agents and tools to provide comprehensive answers.\n\n## Your Capabilities\n- Analyze user intent and determine required actions\n- Route requests to appropriate specialized agents (SQL, Graph)\n- Coordinate multi-step workflows\n- Combine results from multiple agents\n- Provide direct answers for general questions\n\n## Agent Routing Guidelines\n\n### SQL Agent\nRoute to SQL agent for:\n- Data analysis and reporting requests\n- Questions about account performance, sales metrics\n- Requests for specific data queries or reports\n- Trend analysis and statistical questions\n\n### Graph Agent  \nRoute to Graph agent for:\n- Relationship and connection questions\n- Account hierarchy and organizational structure\n- Partnership and collaboration inquiries\n- Network analysis and pattern discovery\n\n### Direct Response\nProvide direct answers for:\n- General knowledge questions not related to proprietary data.\n\n### Multiple Function selection\n- You may select 1 or more tools to call - depending on User question.\n- If user asks about sales data AND relationships, you can call both tools.\n\n\n## Account Extraction Requirement\nFor every agent/tool call (e.g., SQL or Graph agent), you MUST extract the list of account names or aliases explicitly mentioned in the user query. Add these as an array field `accounts_mentioned` (list of strings, or `null` if no accounts are mentioned) in the agent/tool call parameters. If the user query is generic (e.g., \"sum of sales across all accounts\"), set `accounts_mentioned` to `null`.\n\n## Planning Process\n1. **Analyze Request**: Understand user intent and required information\n2. **Determine Agents**: Select appropriate agents based on request type\n3. **Extract Accounts**: Identify and list all account names/aliases mentioned in the query (or set to `null` if none)\n4. **Plan Sequence**: Order agent calls for optimal workflow\n5. **Coordinate Execution**: Manage agent interactions and data flow\n6. **Synthesize Results**: Combine outputs into coherent response\n\n## Multi-Agent Workflows\nFor complex requests that need multiple agents:\n1. Start with broader context (Graph agent for relationships)\n2. Drill down to specific data (SQL agent for metrics)\n3. Combine insights from both perspectives\n4. Provide unified, actionable recommendations\n\n## Response Quality\n- Ensure responses are complete and accurate\n- Maintain conversation context across agent calls\n- Provide clear explanations of methodology\n- Suggest follow-up questions and actions\n\nRemember: Your goal is to provide the most comprehensive and useful response by intelligently orchestrating available agents and tools.\n"
    },
    {
      "role": "user",
      "content": "All sales"
    }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "graph_agent",
        "description": "Graph agent for querying relationships, connections, and account information from the knowledge graph",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string"
            },
            "accounts_mentioned": {
              "type": [
                "array",
                "null"
              ],
              "items": {
                "type": "string"
              }
            }
          },
          "required": [
            "query",
            "accounts_mentioned"
          ]
        }
      }
    },
    {
      "type": "function",
      "function": {
        "name": "sql_agent",
        "description": "SQL agent for querying sales data, revenue metrics, and business analytics from the Fabric Lakehouse",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string"
            },
            "accounts_mentioned": {
              "type": [
                "array",
                "null"
              ],
              "items": {
                "type": "string"
              }
            }
          },
          "required": [
            "query",
            "accounts_mentioned"
          ]
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

### Planner Raw Response

```json
{
  "id": "chatcmpl-CIwS2rnpJOF4dCDH1VwK9ZC4GIiLP",
  "choices": [
    {
      "finish_reason": "tool_calls",
      "index": 0,
      "logprobs": null,
      "message": {
        "content": null,
        "refusal": null,
        "role": "assistant",
        "annotations": [],
        "audio": null,
        "function_call": null,
        "tool_calls": [
          {
            "id": "call_yXYYIa33QwOkTZmu39XFypP8",
            "function": {
              "arguments": "{\"query\":\"Retrieve all sales data across all accounts.\",\"accounts_mentioned\":null}",
              "name": "sql_agent"
            },
            "type": "function"
          }
        ]
      },
      "content_filter_results": {}
    }
  ],
  "created": 1758630626,
  "model": "gpt-4.1-2025-04-14",
  "object": "chat.completion",
  "service_tier": null,
  "system_fingerprint": "fp_9ab7d013ff",
  "usage": {
    "completion_tokens": 27,
    "prompt_tokens": 646,
    "total_tokens": 673,
    "completion_tokens_details": {
      "accepted_prediction_tokens": 0,
      "audio_tokens": 0,
      "reasoning_tokens": 0,
      "rejected_prediction_tokens": 0
    },
    "prompt_tokens_details": {
      "audio_tokens": 0,
      "cached_tokens": 0
    }
  },
  "prompt_filter_results": [
    {
      "prompt_index": 0,
      "content_filter_results": {
        "hate": {
          "filtered": false,
          "severity": "safe"
        },
        "self_harm": {
          "filtered": false,
          "severity": "safe"
        },
        "sexual": {
          "filtered": false,
          "severity": "safe"
        },
        "violence": {
          "filtered": false,
          "severity": "safe"
        }
      }
    }
  ]
}
```

### Planner Tool Calls

- Tool Call → sql_agent

  Arguments: {"query":"Retrieve all sales data across all accounts.","accounts_mentioned":null}


### Agent Request

```json
{
  "messages": [
    {
      "role": "system",
      "content": "# SQL Agent System Prompt\n\nYou are a specialized SQL agent for a Salesforce Q&A chatbot. Your role is to help users query and analyze Salesforce data using SQL.\n\n## Your Capabilities\n- Execute SQL queries against Salesforce data\n- Analyze account performance, sales data, and customer information\n- Generate reports and insights from Salesforce data\n- Help users understand data relationships and trends\n\n## Guidelines\n1. **Always validate user permissions** before executing queries\n2. **Use parameterized queries** to prevent SQL injection\n3. **Limit result sets** to reasonable sizes (default: 100 rows)\n4. **Explain your findings** in business-friendly language\n5. **Suggest follow-up questions** when appropriate\n\n## Query Types You Handle\n- Account performance analysis\n- Sales pipeline reports\n- Customer segmentation queries\n- Opportunity tracking\n- Activity and engagement metrics\n\n## Response Format\nWhen executing SQL queries:\n1. Validate the request and user permissions\n2. Execute the appropriate SQL query\n3. Format results in a clear, readable format\n4. Provide business insights and explanations\n5. Suggest related queries or follow-up actions\n\n## Error Handling\n- If a query fails, explain the issue in user-friendly terms\n- Suggest alternative approaches or corrections\n- Never expose sensitive system information\n\nRemember: Your goal is to make Salesforce data accessible and actionable for business users.\n"
    },
    {
      "role": "user",
      "content": "Retrieve all sales data across all accounts."
    }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "graph_agent_function",
        "description": "Query the knowledge graph to find relationships between accounts, contacts, and business entities",
        "parameters": {
          "type": "object",
          "properties": {
            "account_name": {
              "type": "string",
              "description": "Name of the account to search for"
            },
            "relationship_type": {
              "type": "string",
              "description": "Type of relationship to explore (e.g., 'partner', 'competitor', 'supplier')",
              "enum": [
                "partner",
                "competitor",
                "supplier",
                "customer",
                "vendor"
              ]
            },
            "max_depth": {
              "type": "integer",
              "description": "Maximum traversal depth in the graph",
              "default": 2,
              "maximum": 5
            }
          },
          "required": [
            "account_name"
          ]
        }
      }
    },
    {
      "type": "function",
      "function": {
        "name": "sql_query_function",
        "description": "Execute SQL queries against the Fabric Lakehouse to retrieve sales and account data",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string",
              "description": "The SQL query to execute"
            },
            "limit": {
              "type": "integer",
              "description": "Maximum number of rows to return",
              "default": 100
            }
          },
          "required": [
            "query"
          ]
        }
      }
    },
    {
      "type": "function",
      "function": {
        "name": "sql_agent",
        "description": "SQL agent for querying sales data, revenue metrics, and business analytics from the Fabric Lakehouse",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string",
              "description": "User's natural language query about sales data or business metrics"
            },
            "accounts_mentioned": {
              "type": [
                "array",
                "null"
              ],
              "items": {
                "type": "string"
              },
              "description": "List of account names/aliases mentioned in the query, or null if none."
            }
          },
          "required": [
            "query"
          ]
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

### Agent Raw Response

```json
{
  "id": "chatcmpl-CIwS3KccXx2BZGSmG8OA6KqVXlMZQ",
  "choices": [
    {
      "finish_reason": "tool_calls",
      "index": 0,
      "logprobs": null,
      "message": {
        "content": null,
        "refusal": null,
        "role": "assistant",
        "annotations": [],
        "audio": null,
        "function_call": null,
        "tool_calls": [
          {
            "id": "call_ZmIx46FIMBSoumSpwZuIFMaR",
            "function": {
              "arguments": "{\"query\":\"SELECT AccountName, OpportunityName, Stage, Amount, CloseDate FROM Opportunities ORDER BY CloseDate DESC\",\"limit\":100}",
              "name": "sql_query_function"
            },
            "type": "function"
          }
        ]
      },
      "content_filter_results": {}
    }
  ],
  "created": 1758630627,
  "model": "gpt-4.1-2025-04-14",
  "object": "chat.completion",
  "service_tier": null,
  "system_fingerprint": "fp_c79ab13e31",
  "usage": {
    "completion_tokens": 39,
    "prompt_tokens": 576,
    "total_tokens": 615,
    "completion_tokens_details": {
      "accepted_prediction_tokens": 0,
      "audio_tokens": 0,
      "reasoning_tokens": 0,
      "rejected_prediction_tokens": 0
    },
    "prompt_tokens_details": {
      "audio_tokens": 0,
      "cached_tokens": 0
    }
  },
  "prompt_filter_results": [
    {
      "prompt_index": 0,
      "content_filter_results": {
        "hate": {
          "filtered": false,
          "severity": "safe"
        },
        "self_harm": {
          "filtered": false,
          "severity": "safe"
        },
        "sexual": {
          "filtered": false,
          "severity": "safe"
        },
        "violence": {
          "filtered": false,
          "severity": "safe"
        }
      }
    }
  ]
}
```

### Agent Tool Calls (not executed)

- Tool Call → sql_query_function

  Arguments: {"query":"SELECT AccountName, OpportunityName, Stage, Amount, CloseDate FROM Opportunities ORDER BY CloseDate DESC","limit":100}


---
