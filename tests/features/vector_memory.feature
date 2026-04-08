Feature: Vector Memory semantic retrieval

  Scenario: Storing and retrieving a global memory entry
    Given a fresh VectorMemory instance
    When I store a global entry with key "lang" and value "python"
    Then retrieving key "lang" returns "python"

  Scenario: Semantic search returns relevant entries
    Given a VectorMemory loaded with 10 diverse topic entries
    When I query for "authentication security tokens"
    Then the auth-related entries appear in the result

  Scenario: Task memory is cleared after task completion
    Given a VectorMemory with entries stored under task "task_001"
    When I clear the task memory for "task_001"
    Then no entries are returned for task "task_001"

  Scenario: Backward-compatible agent_context without query
    Given a VectorMemory with global entry "deploy_env" set to "production"
    When I call agent_context without a query parameter
    Then "deploy_env" appears in the returned context
