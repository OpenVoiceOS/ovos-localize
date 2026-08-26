"""AST-based analysis of OVOS skill Python source code.

Extracts:
- @intent_handler decorators (Padatious file refs, Adapt IntentBuilder chains)
- self.speak_dialog() calls with variable names
- self.get_response() / self.ask_yesno() calls
- Mapping of locale files to handler methods
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class IntentHandlerInfo:
    """Information about an @intent_handler-decorated method.

    Attributes:
        method_name: The Python method name.
        file_path: Path to the Python file.
        line_number: Line number of the method definition.
        intent_type: 'padatious' or 'adapt'.
        intent_file: For Padatious — the .intent filename.
        builder_name: For Adapt — the IntentBuilder name.
        required_keywords: For Adapt — list of .require() keyword names.
        optional_keywords: For Adapt — list of .optionally() keyword names.
        one_of_keywords: For Adapt — list of .one_of() keyword groups.
        voc_blacklist: Vocabulary blacklist from decorator kwargs.
    """

    method_name: str
    file_path: str
    line_number: int
    intent_type: str  # "padatious" or "adapt"
    intent_file: str | None = None
    builder_name: str | None = None
    required_keywords: list[str] = field(default_factory=list)
    optional_keywords: list[str] = field(default_factory=list)
    one_of_keywords: list[list[str]] = field(default_factory=list)
    voc_blacklist: list[str] = field(default_factory=list)
    end_line: int = 0
    source_code: str | None = None


@dataclass
class DialogCallInfo:
    """Information about a self.speak_dialog() call.

    Attributes:
        dialog_name: The dialog file key (e.g., 'time.current').
        variables: Variable names passed in the data dict.
        method_name: The handler method containing this call.
        file_path: Path to the Python file.
        line_number: Line number of the call.
    """

    dialog_name: str
    variables: list[str] = field(default_factory=list)
    method_name: str = ""
    file_path: str = ""
    line_number: int = 0


@dataclass
class ResponseCallInfo:
    """Information about self.get_response() or self.ask_yesno() calls.

    Attributes:
        dialog_name: The dialog file key used as prompt.
        call_type: 'get_response' or 'ask_yesno'.
        method_name: The handler method containing this call.
        file_path: Path to the Python file.
        line_number: Line number of the call.
    """

    dialog_name: str
    call_type: str  # "get_response" or "ask_yesno"
    method_name: str = ""
    file_path: str = ""
    line_number: int = 0


@dataclass
class SkillAnalysis:
    """Complete analysis result for a skill's Python source.

    Attributes:
        skill_class_name: The OVOSSkill subclass name found.
        source_file: Path to the main skill Python file.
        intent_handlers: All @intent_handler methods found.
        dialog_calls: All speak_dialog() calls found.
        response_calls: All get_response()/ask_yesno() calls found.
        intent_file_to_handler: Map of .intent filename → handler info.
        voc_to_intents: Map of .voc basename → list of Adapt intents using it.
        dialog_to_callers: Map of dialog key → list of methods that call speak_dialog with it.
    """

    skill_class_name: str = ""
    source_file: str = ""
    intent_handlers: list[IntentHandlerInfo] = field(default_factory=list)
    dialog_calls: list[DialogCallInfo] = field(default_factory=list)
    response_calls: list[ResponseCallInfo] = field(default_factory=list)
    intent_file_to_handler: dict[str, IntentHandlerInfo] = field(default_factory=dict)
    voc_to_intents: dict[str, list[str]] = field(default_factory=dict)
    dialog_to_callers: dict[str, list[str]] = field(default_factory=dict)
    method_sources: dict[str, str] = field(default_factory=dict)


class SkillAnalyzer:
    """AST-based analyzer for OVOS skill Python source files.

    Parses Python source to extract intent handler registrations,
    dialog variable usage, and cross-references between locale files
    and handler methods.
    """

    def analyze_file(self, file_path: str) -> SkillAnalysis:
        """Analyze a single Python source file.

        Args:
            file_path: Path to the Python file.

        Returns:
            SkillAnalysis with all extracted information.
        """
        content = Path(file_path).read_text(encoding="utf-8")
        return self.analyze_source(content, file_path)

    def analyze_source(self, source: str, file_path: str = "") -> SkillAnalysis:
        """Analyze Python source code string.

        Args:
            source: Python source code.
            file_path: Path for reference in results.

        Returns:
            SkillAnalysis with all extracted information.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return SkillAnalysis(source_file=file_path)

        analysis = SkillAnalysis(source_file=file_path)
        source_lines = source.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if self._is_skill_class(node):
                    analysis.skill_class_name = node.name
                    self._analyze_class(node, analysis, file_path, source_lines)
                    break  # Typically one skill class per file

        self._build_indexes(analysis)
        return analysis

    def analyze_directory(self, directory: str) -> SkillAnalysis:
        """Analyze all Python files in a directory, merging results.

        Args:
            directory: Path to directory containing Python files.

        Returns:
            Merged SkillAnalysis from all files.
        """
        merged = SkillAnalysis()
        for py_file in sorted(Path(directory).rglob("*.py")):
            if py_file.name.startswith("_") and py_file.name != "__init__.py":
                continue
            result = self.analyze_file(str(py_file))
            if result.skill_class_name:
                merged.skill_class_name = result.skill_class_name
                merged.source_file = result.source_file
            merged.intent_handlers.extend(result.intent_handlers)
            merged.dialog_calls.extend(result.dialog_calls)
            merged.response_calls.extend(result.response_calls)

        self._build_indexes(merged)
        return merged

    @staticmethod
    def _is_skill_class(node: ast.ClassDef) -> bool:
        """Check if a class definition is an OVOSSkill subclass.

        Args:
            node: AST ClassDef node.

        Returns:
            True if any base class name contains 'Skill'.
        """
        for base in node.bases:
            name = ""
            if isinstance(base, ast.Name):
                name = base.id
            elif isinstance(base, ast.Attribute):
                name = base.attr
            if "Skill" in name:
                return True
        return False

    def _analyze_class(
        self, class_node: ast.ClassDef, analysis: SkillAnalysis, file_path: str,
        source_lines: list[str] | None = None,
    ) -> None:
        """Analyze all methods in a skill class.

        Args:
            class_node: AST ClassDef for the skill.
            analysis: SkillAnalysis to populate.
            file_path: Source file path.
            source_lines: Original source split into lines.
        """
        for node in ast.iter_child_nodes(class_node):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._analyze_method(node, analysis, file_path, source_lines)

    def _analyze_method(
        self, method_node: ast.FunctionDef, analysis: SkillAnalysis, file_path: str,
        source_lines: list[str] | None = None,
    ) -> None:
        """Analyze a single method for intent handlers and dialog calls.

        Args:
            method_node: AST FunctionDef node.
            analysis: SkillAnalysis to populate.
            file_path: Source file path.
            source_lines: Original source split into lines.
        """
        # Extract method source code
        method_source = self._extract_method_source(method_node, source_lines)
        if method_source:
            analysis.method_sources[method_node.name] = method_source

        # Check decorators for @intent_handler
        for decorator in method_node.decorator_list:
            handler_info = self._parse_intent_handler_decorator(
                decorator, method_node.name, file_path, method_node.lineno
            )
            if handler_info:
                handler_info.end_line = getattr(method_node, 'end_lineno', 0) or 0
                handler_info.source_code = method_source
                analysis.intent_handlers.append(handler_info)

        # Walk method body for speak_dialog, get_response, ask_yesno
        for node in ast.walk(method_node):
            if not isinstance(node, ast.Call):
                continue

            call_name = self._get_self_call_name(node)
            if not call_name:
                continue

            if call_name == "speak_dialog":
                info = self._parse_dialog_call(node, method_node.name, file_path)
                if info:
                    analysis.dialog_calls.append(info)

            elif call_name in ("get_response", "ask_yesno"):
                info = self._parse_response_call(
                    node, call_name, method_node.name, file_path
                )
                if info:
                    analysis.response_calls.append(info)

    def _parse_intent_handler_decorator(
        self, decorator: ast.expr, method_name: str, file_path: str, line_number: int
    ) -> IntentHandlerInfo | None:
        """Parse an @intent_handler decorator.

        Args:
            decorator: AST node for the decorator.
            method_name: Name of the decorated method.
            file_path: Source file path.
            line_number: Line number of the method.

        Returns:
            IntentHandlerInfo or None if not an intent_handler decorator.
        """
        # Match @intent_handler(...) call
        if not isinstance(decorator, ast.Call):
            return None

        dec_name = ""
        if isinstance(decorator.func, ast.Name):
            dec_name = decorator.func.id
        elif isinstance(decorator.func, ast.Attribute):
            dec_name = decorator.func.attr

        if dec_name != "intent_handler":
            return None

        if not decorator.args:
            return None

        arg = decorator.args[0]

        # Case 1: @intent_handler("filename.intent") — Padatious
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            intent_file = arg.value
            voc_blacklist = self._extract_keyword_arg_list(decorator, "voc_blacklist")
            return IntentHandlerInfo(
                method_name=method_name,
                file_path=file_path,
                line_number=line_number,
                intent_type="padatious",
                intent_file=str(intent_file),
                voc_blacklist=voc_blacklist,
            )

        # Case 2: @intent_handler(IntentBuilder(...).require(...).optionally(...))
        if isinstance(arg, ast.Call):
            return self._parse_intent_builder_chain(
                arg, method_name, file_path, line_number
            )

        return None

    def _parse_intent_builder_chain(
        self, node: ast.Call, method_name: str, file_path: str, line_number: int
    ) -> IntentHandlerInfo | None:
        """Parse an IntentBuilder(...).require(...).optionally(...) chain.

        Args:
            node: AST Call node at the end of the chain.
            method_name: Method name.
            file_path: Source file path.
            line_number: Line number.

        Returns:
            IntentHandlerInfo or None.
        """
        required: list[str] = []
        optional: list[str] = []
        one_of: list[list[str]] = []
        builder_name = ""

        current = node
        while isinstance(current, ast.Call):
            func_name = ""
            if isinstance(current.func, ast.Attribute):
                func_name = current.func.attr
                current_next = current.func.value
            elif isinstance(current.func, ast.Name):
                func_name = current.func.id
                current_next = None
            else:
                break

            if func_name == "IntentBuilder" and current.args:
                arg = current.args[0]
                if isinstance(arg, ast.Constant):
                    builder_name = str(arg.value)
                break

            if func_name == "require" and current.args:
                val = self._get_string_value(current.args[0])
                if val:
                    required.append(val)
            elif func_name == "optionally" and current.args:
                val = self._get_string_value(current.args[0])
                if val:
                    optional.append(val)
            elif func_name == "one_of" and current.args:
                group = [
                    self._get_string_value(a)
                    for a in current.args
                    if self._get_string_value(a)
                ]
                if group:
                    one_of.append(group)
            elif func_name == "build":
                pass  # .build() is terminal, continue traversing

            if current_next is None:
                break
            current = current_next

        if not builder_name and not required:
            return None

        return IntentHandlerInfo(
            method_name=method_name,
            file_path=file_path,
            line_number=line_number,
            intent_type="adapt",
            builder_name=builder_name,
            required_keywords=required,
            optional_keywords=optional,
            one_of_keywords=one_of,
        )

    def _parse_dialog_call(
        self, node: ast.Call, method_name: str, file_path: str
    ) -> DialogCallInfo | None:
        """Parse a self.speak_dialog() call.

        Args:
            node: AST Call node.
            method_name: Containing method name.
            file_path: Source file path.

        Returns:
            DialogCallInfo or None.
        """
        if not node.args:
            return None

        dialog_name = self._get_string_value(node.args[0])
        if not dialog_name:
            return None

        variables: list[str] = []
        # Look for dict literal as second arg or 'data' keyword
        dict_node = None
        if len(node.args) > 1 and isinstance(node.args[1], ast.Dict):
            dict_node = node.args[1]
        else:
            for kw in node.keywords:
                if kw.arg == "data" and isinstance(kw.value, ast.Dict):
                    dict_node = kw.value
                    break

        if dict_node:
            for key in dict_node.keys:
                if key is not None:
                    val = self._get_string_value(key)
                    if val:
                        variables.append(val)

        return DialogCallInfo(
            dialog_name=dialog_name,
            variables=variables,
            method_name=method_name,
            file_path=file_path,
            line_number=node.lineno,
        )

    def _parse_response_call(
        self, node: ast.Call, call_type: str, method_name: str, file_path: str
    ) -> ResponseCallInfo | None:
        """Parse a self.get_response() or self.ask_yesno() call.

        Args:
            node: AST Call node.
            call_type: 'get_response' or 'ask_yesno'.
            method_name: Containing method name.
            file_path: Source file path.

        Returns:
            ResponseCallInfo or None.
        """
        if not node.args:
            return None

        dialog_name = self._get_string_value(node.args[0])
        if not dialog_name:
            return None

        return ResponseCallInfo(
            dialog_name=dialog_name,
            call_type=call_type,
            method_name=method_name,
            file_path=file_path,
            line_number=node.lineno,
        )

    @staticmethod
    def _get_self_call_name(node: ast.Call) -> str | None:
        """Extract method name from self.method_name() calls.

        Args:
            node: AST Call node.

        Returns:
            Method name string or None.
        """
        if (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "self"
        ):
            return node.func.attr
        return None

    @staticmethod
    def _get_string_value(node: ast.expr) -> str | None:
        """Extract string value from an AST node.

        Args:
            node: AST expression node.

        Returns:
            String value or None.
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    @staticmethod
    def _extract_keyword_arg_list(call: ast.Call, kwarg_name: str) -> list[str]:
        """Extract a list of strings from a keyword argument.

        Args:
            call: AST Call node.
            kwarg_name: Name of the keyword argument.

        Returns:
            List of string values.
        """
        for kw in call.keywords:
            if kw.arg == kwarg_name and isinstance(kw.value, (ast.List, ast.Tuple)):
                result = []
                for elt in kw.value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        result.append(elt.value)
                return result
        return []

    @staticmethod
    def _extract_method_source(
        method_node: ast.FunctionDef, source_lines: list[str] | None
    ) -> str | None:
        """Extract the source code of a method from the original source lines.

        Includes decorator lines. Caps at 40 lines to keep JSON manageable.

        Args:
            method_node: AST FunctionDef node.
            source_lines: Original source split into lines.

        Returns:
            Method source code string, or None.
        """
        if not source_lines:
            return None

        # Include decorators — find the earliest decorator line
        start = method_node.lineno  # 1-based
        if method_node.decorator_list:
            start = min(d.lineno for d in method_node.decorator_list)

        end = getattr(method_node, 'end_lineno', None)
        if not end:
            return None

        # Convert to 0-based indexing, cap at 40 lines
        lines = source_lines[start - 1 : min(end, start - 1 + 40)]
        if end > start - 1 + 40:
            lines.append("        # ... (truncated)")

        # Dedent: find minimum indentation
        non_empty = [ln for ln in lines if ln.strip()]
        if non_empty:
            min_indent = min(len(ln) - len(ln.lstrip()) for ln in non_empty)
            lines = [ln[min_indent:] if len(ln) > min_indent else ln for ln in lines]

        return "\n".join(lines)

    @staticmethod
    def _build_indexes(analysis: SkillAnalysis) -> None:
        """Build cross-reference indexes from raw analysis data.

        Args:
            analysis: SkillAnalysis to update in place.
        """
        # intent file → handler
        for handler in analysis.intent_handlers:
            if handler.intent_file:
                analysis.intent_file_to_handler[handler.intent_file] = handler

        # voc → intents (Adapt keywords)
        for handler in analysis.intent_handlers:
            if handler.intent_type == "adapt":
                for kw in handler.required_keywords + handler.optional_keywords:
                    analysis.voc_to_intents.setdefault(kw, []).append(
                        handler.builder_name or handler.method_name
                    )

        # dialog → callers
        for call in analysis.dialog_calls:
            analysis.dialog_to_callers.setdefault(call.dialog_name, []).append(
                call.method_name
            )
        for call in analysis.response_calls:
            analysis.dialog_to_callers.setdefault(call.dialog_name, []).append(
                call.method_name
            )
