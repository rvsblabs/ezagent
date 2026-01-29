# Introduction

During development, I noticed that implementing a MCP based agentic workflow is pretty difficult. It involves many component and most of the time, when shifting company to company, the core agentic use case remains the same.

Agent is something that has access to the following 
    1. Memory
    2. Skills
    3. Tools

Multi Agent system is something that has many agents that are able to communicate with other agents.

# Goal

My Goal over here is to develop a developer sdk that allows creation of agents in low code/no code manner. It should have the following commands:

1. ez start - starts the agents as server.
2. ez stop - stops the agents as server.
3. ez init <app_name> - initializes scaffold files to allow for development.

# Structure

ez init creates a structure like this - 

app_name/
    tools/
    skills/
    agents.yml

tools and skills can be empty directories.

agents.yml has a structure something like this (notice that agents can themselves be tools) - 

agents:
    agent_1:
        tools: pdf_reader, csv_reader, summarization, memory, agent_2
        skills: write_concise, summarize, research
        description: "Description of what the agent does"
    agent_2:
        tools: pdf_reader, web_search
        skills: google_expert
        description: "Agent that expertly searches google for pdf"

tools directory will look something like this - 
tools/
    pdf_reader/
        main.py (mcp tool using fast_mcp)
    csv_reader/
        main.py (mcp tool exposed using fast_mcp)

skills directory will look something like this -
skills/
    write_concise.md
    summarize.md
    research.md

# Goal
We would like to develop a scalable system that initially works with anthropic api to implement this, however keep it scalable to different providers so that we are able to scale easier.

For MCP - use fastmcp
For Skills - not sure, do your own research

Once we run ez start, anywhere in any terminal, it should allow me to use ez command to interact with any agent, e.g. ez agent_1 read me xyz file and generate summary of documents in this file.
