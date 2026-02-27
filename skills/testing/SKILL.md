---
name: Test Generator
description: Generates comprehensive test suites following testing best practices
---

# Test Generator Skill

When generating tests, follow these principles:

## Test Structure
- Use AAA pattern: Arrange, Act, Assert
- One assertion per test when practical
- Descriptive test names that explain the scenario

## Coverage Areas
1. **Happy path**: Normal expected behavior
2. **Edge cases**: Boundary values, empty inputs, null values
3. **Error cases**: Invalid inputs, exceptions, error handling
4. **Integration**: Component interactions

## Framework Guidelines
- Python: Use pytest with fixtures and parametrize
- JavaScript/TypeScript: Use Jest or Vitest
- Follow the project's existing test patterns

## Output
- Generate complete, runnable test files
- Include setup/teardown when needed
- Add comments explaining test rationale
