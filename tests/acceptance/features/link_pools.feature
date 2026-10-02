@story:LINKS-1 @story:LINKS-2 @story:LINKS-3
Feature: Reserved short links owned by an organization
  Scenario: Activate a link after a visitor subscribes
    Given an organization has reserved a link without a destination
    When a visitor subscribes with an email address
    And the organization registers a valid destination
    Then the original short link redirects to that destination
    And one durable activation email is waiting for delivery

  Scenario: Repeated subscriptions do not cause repeated notifications
    Given an organization has reserved a link without a destination
    When a visitor submits the same email address twice
    And the organization registers a valid destination
    Then one durable activation email is waiting for delivery
