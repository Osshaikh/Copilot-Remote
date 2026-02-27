---
name: Security Audit
description: Identifies security vulnerabilities and suggests fixes following OWASP guidelines
---

# Security Audit Skill

When auditing code for security:

## Check For
1. **Injection**: SQL, XSS, command injection
2. **Authentication**: Weak auth, missing validation
3. **Data Exposure**: Sensitive data in logs, responses
4. **Input Validation**: Missing or insufficient validation
5. **Dependencies**: Known vulnerable packages
6. **Configuration**: Insecure defaults, hardcoded secrets

## Severity Levels
- **Critical**: Immediately exploitable, high impact
- **High**: Exploitable with some effort
- **Medium**: Potential vulnerability under specific conditions
- **Low**: Best practice violation, minimal risk

## Output Format
For each finding:
- Severity level
- Description of the vulnerability
- Location in code
- Proof of concept (if applicable)
- Recommended fix with code example
- References (CWE, OWASP)
