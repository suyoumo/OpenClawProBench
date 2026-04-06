# Validation Policy

- Keep recall at 100 percent.
- Peak memory must stay at or below 0.8 GB.
- Only these count as true vulnerabilities:
  - hardcoded secrets directly assigned in checked-in source
  - bearer or token values written into logs
- Exclude these from the true-positive list:
  - environment-variable reads
  - comments or descriptive text
  - runtime template strings that interpolate a token instead of hardcoding one
