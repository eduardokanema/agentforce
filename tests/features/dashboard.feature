Feature: Mission Dashboard
  As a developer running AgentForce missions
  I want a browser dashboard to observe agent activity
  So that I can monitor missions without polling the CLI

  Scenario: Listing all missions
    Given two missions exist
    When I render the mission list
    Then the page contains both mission IDs
    And the page contains each mission status badge

  Scenario: Viewing a mission with tasks in various states
    Given a mission with tasks in pending, in_progress, and review_approved states
    When I render the mission detail page
    Then I see each task listed with its status
    And I see the progress stats showing 1 of 3 tasks approved

  Scenario: Viewing a reviewed and approved task
    Given a task has been reviewed and approved with score 8
    When I render the task detail page
    Then I see the review score 8
    And I see the reviewer feedback text
    And I see the worker output

  Scenario: Rejected task shows blocking issues
    Given a task was rejected with blocking issues
    When I render the task detail page
    Then I see the review_rejected status
    And I see each blocking issue listed

  Scenario: Mission progress fraction is visible
    Given a mission has 3 approved tasks and 2 pending tasks
    When I render the mission detail page
    Then I see 3 of 5 tasks in the stats
