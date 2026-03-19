# Suggestions for ovos-localize

## Refactoring Proposals

### Migrate `ast.Str` to `ast.Constant`
- **Description**: Update `ast_analyzer.py` to use `ast.Constant` instead of the deprecated `ast.Str`.
- **Benefit**: Future-proof against removal in Python 3.14.
- **Complexity**: Low.

### Standardize Type Hints
- **Description**: Improve coverage of type hints across the project to reach 100% compliance.
- **Benefit**: Improved developer experience and catch more static errors.
