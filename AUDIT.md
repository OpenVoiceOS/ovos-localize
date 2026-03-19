# Audit Report - ovos-localize

## Known Issues & Technical Debt

### Deprecation: `ast.Str` usage
- **Location**: `ovos_localize/analyzers/ast_analyzer.py:300`
- **Issue**: `ast.Str` is deprecated in Python 3.12 and will be removed in Python 3.14.
- **Evidence**: `DeprecationWarning: ast.Str is deprecated and will be removed in Python 3.14; use ast.Constant instead`
- **Impact**: Code will break on Python 3.14+.
