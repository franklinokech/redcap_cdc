# validators.py
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import re
import operator
import warnings


@dataclass
class FieldSchema:
    # =====================================================
    # IDENTITY
    # =====================================================
    field_name: str
    form_name: Optional[str] = None
    field_label: Optional[str] = None

    # =====================================================
    # TYPE SYSTEM
    # =====================================================
    field_type: str = "unknown"
    validation_type: Optional[str] = None

    # =====================================================
    # CONSTRAINTS
    # =====================================================
    required: bool = False
    min_value: Optional[float] = None
    max_value: Optional[float] = None

    # =====================================================
    # CATEGORICAL
    # =====================================================
    choices: Optional[Dict[str, str]] = None

    # =====================================================
    # LOGIC
    # =====================================================
    branching_logic: Optional[str] = None

    # =====================================================
    # PRIVACY / GOVERNANCE
    # =====================================================
    is_pii: bool = False

    # =====================================================
    # METADATA
    # =====================================================
    field_note: Optional[str] = None
    section_header: Optional[str] = None
    field_annotation: Optional[str] = None

    # =====================================================
    # DERIVED CLASSIFICATIONS (AUTO-COMPUTED)
    # =====================================================

    @property
    def is_system(self) -> bool:
        """REDCap system/internal fields (record_id is NOT system, it's user-facing)"""
        return self.field_name in {
            "record_id",
            "redcap_event_name",
            "redcap_repeat_instrument",
            "redcap_repeat_instance",
            "redcap_data_access_group",
            "user_name",
            "user_dag_name",
        }

    @property
    def is_calculated(self) -> bool:
        """Calculated fields should not be validated directly"""
        return self.field_type == "calc"

    @property
    def is_checkbox(self) -> bool:
        return self.field_type == "checkbox"

    @property
    def is_text(self) -> bool:
        return self.field_type == "text"

    @property
    def is_required_for_qc(self) -> bool:
        """Determines if this field should be validated"""
        return not (self.is_system or self.is_calculated)

    # =====================================================
    # DATE/TIME VALIDATION TYPES
    # =====================================================

    @property
    def date_format_category(self) -> Optional[str]:
        """
        Returns the category of date/time validation:
        'date', 'datetime', 'datetime_seconds', 'time', 'time_seconds'
        """
        if not self.validation_type:
            return None

        val = self.validation_type.lower()

        if val.startswith('datetime_seconds'):
            return 'datetime_seconds'
        elif val.startswith('datetime'):
            return 'datetime'
        elif val.startswith('date'):
            return 'date'
        elif val.startswith('time_seconds'):
            return 'time_seconds'
        elif val.startswith('time'):
            return 'time'

        return None

    @property
    def date_order(self) -> Optional[str]:
        """
        Returns the date order format:
        'ymd' (Y-M-D), 'mdy' (M-D-Y), 'dmy' (D-M-Y)
        """
        if not self.validation_type:
            return None

        val = self.validation_type.lower()

        if val.endswith('_ymd'):
            return 'ymd'
        elif val.endswith('_mdy'):
            return 'mdy'
        elif val.endswith('_dmy'):
            return 'dmy'
        elif val == 'date':
            return 'ymd'
        elif val == 'datetime':
            return 'ymd'
        elif val == 'datetime_seconds':
            return 'ymd'

        return None

    @property
    def date_format_string(self) -> Optional[str]:
        """Returns Python datetime format string for validation"""
        category = self.date_format_category
        order = self.date_order

        format_map = {
            ('date', 'ymd'): "%Y-%m-%d",
            ('date', 'mdy'): "%m/%d/%Y",
            ('date', 'dmy'): "%d/%m/%Y",
            ('date', None): "%Y-%m-%d",

            ('datetime', 'ymd'): "%Y-%m-%d %H:%M",
            ('datetime', 'mdy'): "%m/%d/%Y %H:%M",
            ('datetime', 'dmy'): "%d/%m/%Y %H:%M",
            ('datetime', None): "%Y-%m-%d %H:%M",

            ('datetime_seconds', 'ymd'): "%Y-%m-%d %H:%M:%S",
            ('datetime_seconds', 'mdy'): "%m/%d/%Y %H:%M:%S",
            ('datetime_seconds', 'dmy'): "%d/%m/%Y %H:%M:%S",
            ('datetime_seconds', None): "%Y-%m-%d %H:%M:%S",

            ('time', None): "%H:%M",
            ('time_seconds', None): "%H:%M:%S",
        }

        return format_map.get((category, order))

    @property
    def display_format_example(self) -> Optional[str]:
        """Returns an example of the expected format for display"""
        fmt = self.date_format_string
        if not fmt:
            return None

        example_map = {
            "%Y-%m-%d": "2024-01-15",
            "%m/%d/%Y": "01/15/2024",
            "%d/%m/%Y": "15/01/2024",
            "%Y-%m-%d %H:%M": "2024-01-15 14:30",
            "%m/%d/%Y %H:%M": "01/15/2024 14:30",
            "%d/%m/%Y %H:%M": "15/01/2024 14:30",
            "%Y-%m-%d %H:%M:%S": "2024-01-15 14:30:45",
            "%m/%d/%Y %H:%M:%S": "01/15/2024 14:30:45",
            "%d/%m/%Y %H:%M:%S": "15/01/2024 14:30:45",
            "%H:%M": "14:30",
            "%H:%M:%S": "14:30:45",
        }

        return example_map.get(fmt)

    @property
    def is_date(self) -> bool:
        """Check if field is any date/datetime type"""
        return self.date_format_category in ['date', 'datetime', 'datetime_seconds']

    @property
    def is_time(self) -> bool:
        """Check if field is any time type"""
        return self.date_format_category in ['time', 'time_seconds']

    @property
    def is_datetime(self) -> bool:
        """Check if field includes both date and time"""
        return self.date_format_category in ['datetime', 'datetime_seconds']

    @property
    def includes_seconds(self) -> bool:
        """Check if field includes seconds"""
        return self.date_format_category in ['datetime_seconds', 'time_seconds']

    @property
    def is_email(self) -> bool:
        return self.validation_type == "email"

    @property
    def is_phone(self) -> bool:
        return self.validation_type in ["phone", "phone_us"]

    @property
    def is_numeric(self) -> bool:
        """Check if field represents a number (by field type or validation)"""
        numeric_field_types = {"integer", "number", "float"}
        numeric_validations = {"integer", "int", "number", "float", "decimal"}

        result = (
                self.field_type in numeric_field_types
                or (self.validation_type and self.validation_type.lower() in numeric_validations)
        )
        return bool(result)

    @property
    def has_choices(self) -> bool:
        return bool(self.choices)

    @property
    def has_range(self) -> bool:
        return self.min_value is not None or self.max_value is not None

    @property
    def display_type(self) -> str:
        """Human-readable display type with format example"""
        if self.is_date:
            order = self.date_order or 'ymd'
            if self.date_format_category == 'datetime_seconds':
                example = self.display_format_example or "YYYY-MM-DD HH:MM:SS"
                if order == 'dmy':
                    return f"datetime with seconds (DD/MM/YYYY HH:MM:SS) e.g., {example}"
                elif order == 'mdy':
                    return f"datetime with seconds (MM/DD/YYYY HH:MM:SS) e.g., {example}"
                else:
                    return f"datetime with seconds (YYYY-MM-DD HH:MM:SS) e.g., {example}"
            elif self.date_format_category == 'datetime':
                example = self.display_format_example or "YYYY-MM-DD HH:MM"
                if order == 'dmy':
                    return f"datetime (DD/MM/YYYY HH:MM) e.g., {example}"
                elif order == 'mdy':
                    return f"datetime (MM/DD/YYYY HH:MM) e.g., {example}"
                else:
                    return f"datetime (YYYY-MM-DD HH:MM) e.g., {example}"
            else:
                example = self.display_format_example or "YYYY-MM-DD"
                if order == 'dmy':
                    return f"date (DD/MM/YYYY) e.g., {example}"
                elif order == 'mdy':
                    return f"date (MM/DD/YYYY) e.g., {example}"
                else:
                    return f"date (YYYY-MM-DD) e.g., {example}"

        if self.is_time:
            if self.includes_seconds:
                return f"time (HH:MM:SS) e.g., {self.display_format_example or '14:30:45'}"
            return f"time (HH:MM) e.g., {self.display_format_example or '14:30'}"

        if self.is_numeric:
            return "numeric"
        if self.has_choices:
            return f"dropdown ({len(self.choices)} options)"
        if self.is_email:
            return "email"
        if self.is_phone:
            return "phone"
        return self.field_type or "text"

    def validate_date_string(self, value: str) -> Tuple[bool, Optional[str], Optional[datetime]]:
        """Validate a date string against the field's date format"""
        if not value:
            return True, None, None

        if not self.is_date:
            return True, None, None

        fmt = self.date_format_string
        if not fmt:
            return False, f"Unknown date format for validation type: {self.validation_type}", None

        try:
            dt = datetime.strptime(str(value), fmt)
            return True, None, dt
        except ValueError:
            example = self.display_format_example or fmt
            return False, f"Expected format: {example}", None

    def validate_time_string(self, value: str) -> Tuple[bool, Optional[str], Optional[datetime]]:
        """Validate a time string against the field's time format"""
        if not value:
            return True, None, None

        if not self.is_time:
            return True, None, None

        fmt = self.date_format_string
        if not fmt:
            return False, f"Unknown time format for validation type: {self.validation_type}", None

        try:
            dt = datetime.strptime(str(value), fmt)
            if fmt == "%H:%M" or fmt == "%H:%M:%S":
                hours = int(str(value).split(':')[0])
                if hours < 0 or hours > 23:
                    return False, "Hours must be between 00 and 23", None
            return True, None, dt
        except ValueError:
            example = self.display_format_example or fmt
            return False, f"Expected format: {example}", None

    def get_field_info(self) -> Dict[str, Any]:
        """Comprehensive field information for debugging"""
        return {
            "field_name": self.field_name,
            "field_type": self.field_type,
            "validation_type": self.validation_type,
            "display_type": self.display_type,
            "display_format_example": self.display_format_example,
            "is_required": self.required,
            "is_numeric": self.is_numeric,
            "is_date": self.is_date,
            "is_time": self.is_time,
            "is_datetime": self.is_datetime,
            "includes_seconds": self.includes_seconds,
            "date_format_category": self.date_format_category,
            "date_order": self.date_order,
            "date_format_string": self.date_format_string,
            "has_choices": self.has_choices,
            "has_range": self.has_range,
            "is_calculated": self.is_calculated,
            "is_system": self.is_system,
            "is_pii": self.is_pii,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "choices_count": len(self.choices) if self.choices else 0,
            "branching_logic_present": bool(self.branching_logic),
        }


class SafeEvaluator:
    """Safe evaluation of branching logic with date support"""

    OPERATORS = {
        '==': operator.eq,
        '!=': operator.ne,
        '<>': operator.ne,
        '>': operator.gt,
        '>=': operator.ge,
        '<': operator.lt,
        '<=': operator.le,
        'and': lambda x, y: x and y,
        'or': lambda x, y: x or y,
    }

    def __init__(self, schema: Dict[str, FieldSchema]):
        self.schema = schema

    def parse_date(self, date_str: str, field_name: str = None) -> Optional[float]:
        """Parse date string to timestamp for comparison with safe error handling"""
        if not date_str:
            return None

        date_str = str(date_str).strip("'\"").strip()

        # Skip invalid values
        if not date_str or date_str.lower() in ['null', 'none', 'nan', '']:
            return None

        # Check for obviously weird dates (like 0000-00-00, 9999-99-99, etc.)
        import re
        if re.match(r'^0{4}[-\/]0{2}[-\/]0{2}', date_str):  # 0000-00-00
            return None
        if re.match(r'^9{4}[-\/]9{2}[-\/]9{2}', date_str):  # 9999-99-99
            return None

        if field_name and field_name in self.schema:
            schema = self.schema[field_name]
            if schema.date_format_string:
                try:
                    dt = datetime.strptime(date_str, schema.date_format_string)
                    # Validate reasonable year range (1900-2100)
                    if hasattr(dt, 'year') and (dt.year < 1900 or dt.year > 2100):
                        return None  # Skip unreasonable dates
                    return dt.timestamp()
                except (ValueError, OSError, OverflowError):
                    pass  # Continue to try other formats

        date_formats = [
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%m/%d/%Y",
            "%m/%d/%Y %H:%M:%S",
            "%m/%d/%Y %H:%M",
            "%d/%m/%Y",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%H:%M:%S",
            "%H:%M",
        ]

        for fmt in date_formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                # Validate reasonable year range
                if hasattr(dt, 'year'):
                    if dt.year < 1900 or dt.year > 2100:
                        continue  # Skip unreasonable dates
                return dt.timestamp()
            except (ValueError, OSError, OverflowError, TypeError):
                continue

        return None

    def calculate_datediff(self, date1: str, date2: str, unit: str, signed: int = 1) -> float:
        """Calculate difference between two dates with safe error handling"""
        # Handle None or invalid dates
        if not date1 or not date2:
            return 0

        # Convert to string and clean
        date1 = str(date1).strip()
        date2 = str(date2).strip()

        if not date1 or not date2:
            return 0

        ts1 = self.parse_date(date1)
        ts2 = self.parse_date(date2)

        if ts1 is None or ts2 is None:
            return 0

        try:
            diff_seconds = ts1 - ts2
            diff_days = diff_seconds / 86400

            if unit == 'd':
                diff = diff_days
            elif unit == 'm':
                diff = diff_days / 30.44
            elif unit == 'y':
                diff = diff_days / 365.25
            elif unit == 'h':
                diff = diff_seconds / 3600
            elif unit == 'mi':
                diff = diff_seconds / 60
            else:
                diff = diff_days

            if signed == 0:
                diff = abs(diff)

            return diff
        except (TypeError, OverflowError, ValueError):
            return 0

    def tokenize(self, expression: str) -> List[str]:
        """Tokenize the logic expression"""
        tokens = []
        current = ""

        i = 0
        while i < len(expression):
            char = expression[i]

            if i + 1 < len(expression) and expression[i:i + 2] in ['>=', '<=', '==', '!=', '<>']:
                if current.strip():
                    tokens.append(current.strip())
                    current = ""
                tokens.append(expression[i:i + 2])
                i += 2
                continue

            if char in '()':
                if current.strip():
                    tokens.append(current.strip())
                    current = ""
                tokens.append(char)
                i += 1
                continue

            if char in '><=':
                if current.strip():
                    tokens.append(current.strip())
                    current = ""
                tokens.append(char)
                i += 1
                continue

            if char == ' ':
                if current.strip():
                    tokens.append(current.strip())
                    current = ""
                i += 1
                continue

            current += char
            i += 1

        if current.strip():
            tokens.append(current.strip())

        return tokens

    def parse_tokens(self, tokens: List[str]) -> Any:
        """Parse tokens into an AST and evaluate with operator precedence"""
        if not tokens:
            return None

        while '(' in tokens:
            open_idx = None
            close_idx = None

            for i, token in enumerate(tokens):
                if token == '(':
                    open_idx = i
                elif token == ')' and open_idx is not None:
                    close_idx = i
                    break

            if open_idx is not None and close_idx is not None:
                inner_tokens = tokens[open_idx + 1:close_idx]
                inner_result = self.parse_tokens(inner_tokens)
                tokens = tokens[:open_idx] + [str(inner_result)] + tokens[close_idx + 1:]

        for op in ['>=', '<=', '==', '!=', '<>', '>', '<']:
            while op in tokens:
                idx = tokens.index(op)
                left = self._evaluate_comparand(tokens[idx - 1])
                right = self._evaluate_comparand(tokens[idx + 1])
                result = self.OPERATORS[op](left, right)
                tokens = tokens[:idx - 1] + [str(result)] + tokens[idx + 2:]

        while 'and' in tokens:
            idx = tokens.index('and')
            left = self._parse_value(tokens[idx - 1])
            right = self._parse_value(tokens[idx + 1])
            result = left and right
            tokens = tokens[:idx - 1] + [str(result)] + tokens[idx + 2:]

        while 'or' in tokens:
            idx = tokens.index('or')
            left = self._parse_value(tokens[idx - 1])
            right = self._parse_value(tokens[idx + 1])
            result = left or right
            tokens = tokens[:idx - 1] + [str(result)] + tokens[idx + 2:]

        if len(tokens) == 1:
            return self._parse_value(tokens[0])

        return None

    def _evaluate_comparand(self, token: str) -> Any:
        if token.startswith('datediff('):
            return self._evaluate_datediff(token)
        return self._parse_value(token)

    def _evaluate_datediff(self, datediff_str: str) -> float:
        match = re.match(r'datediff\(([^,]+),\s*([^,]+),\s*\'([^\']+)\',\s*(\d+)\)', datediff_str)
        if not match:
            return 0

        date1_expr = match.group(1).strip()
        date2_expr = match.group(2).strip()
        unit = match.group(3)
        signed = int(match.group(4))

        date1 = self._extract_value(date1_expr)
        date2 = self._extract_value(date2_expr)

        return self.calculate_datediff(date1, date2, unit, signed)

    def _extract_value(self, expr: str) -> str:
        expr = expr.strip()
        field_match = re.match(r'\[([^\]]+)\]', expr)
        if field_match:
            return f"__FIELD__{field_match.group(1)}"
        return expr.strip("'\"")

    def _parse_value(self, token: str) -> Any:
        token = token.strip()

        if token.lower() == 'true':
            return True
        if token.lower() == 'false':
            return False
        if token.lower() in ['null', 'none']:
            return None

        try:
            if re.match(r'^-?\d+(?:\.\d+)?$', token):
                if '.' in token:
                    return float(token)
                return int(token)
        except ValueError:
            pass

        if re.match(r'\d{4}-\d{2}-\d{2}', token) or re.match(r'\d{2}/\d{2}/\d{4}', token):
            timestamp = self.parse_date(token)
            if timestamp is not None:
                return timestamp

        if (token.startswith("'") and token.endswith("'")) or (token.startswith('"') and token.endswith('"')):
            return token[1:-1]

        return token

    def evaluate(self, logic: str, record: Dict[str, Any]) -> bool:
        """Evaluate branching logic expression"""
        if not logic or not logic.strip():
            return True

        processed_logic = logic

        # Convert date literals to timestamps
        date_literals = re.findall(r"['\"]([0-9]{4}-[0-9]{2}-[0-9]{2}[^'\"]*)['\"]", processed_logic)
        for date_literal in date_literals:
            timestamp = self.parse_date(date_literal)
            if timestamp is not None:
                processed_logic = processed_logic.replace(f"'{date_literal}'", str(timestamp))
                processed_logic = processed_logic.replace(f'"{date_literal}"', str(timestamp))

        # Replace field references
        field_refs = re.findall(r'\[([^\]]+)\]', logic)

        for field_ref in field_refs:
            value = record.get(field_ref)
            schema = self.schema.get(field_ref)

            # Handle empty/None values
            if value is None or value == "":
                value_repr = "None"
            elif schema and schema.is_date:
                timestamp = self.parse_date(str(value), field_ref)
                value_repr = str(timestamp) if timestamp is not None else "None"
            elif schema and schema.is_numeric:
                try:
                    num_value = float(value)
                    value_repr = str(int(num_value)) if num_value.is_integer() else str(num_value)
                except (ValueError, TypeError):
                    value_repr = "None"
            elif isinstance(value, str):
                # Keep as string with quotes
                escaped_value = value.replace("'", "\\'")
                value_repr = f"'{escaped_value}'"
            elif isinstance(value, (int, float)):
                value_repr = str(value)
            elif isinstance(value, bool):
                value_repr = str(value)
            else:
                value_repr = "None"

            processed_logic = processed_logic.replace(f'[{field_ref}]', value_repr)

        # Handle REDCap-specific syntax
        processed_logic = processed_logic.replace("is not null", "is not None")
        processed_logic = processed_logic.replace("is null", "is None")
        processed_logic = re.sub(r'(\w+)\s+in\s+\(([^)]+)\)', r'\1 in (\2)', processed_logic)

        # Handle operator conversion - CRITICAL FIX
        # First, protect multi-character operators with placeholders
        processed_logic = processed_logic.replace('<=', '☃LE☃')
        processed_logic = processed_logic.replace('>=', '☃GE☃')
        processed_logic = processed_logic.replace('!=', '☃NE☃')
        processed_logic = processed_logic.replace('<>', '☃NE☃')
        processed_logic = processed_logic.replace('==', '☃EQ☃')

        # Replace standalone = with ==
        processed_logic = re.sub(r'(?<![<>!])=(?![=>])', '==', processed_logic)

        # Restore protected operators
        processed_logic = processed_logic.replace('☃EQ☃', '==')
        processed_logic = processed_logic.replace('☃NE☃', '!=')
        processed_logic = processed_logic.replace('☃LE☃', '<=')
        processed_logic = processed_logic.replace('☃GE☃', '>=')

        # Handle datediff functions
        datediff_pattern = r"datediff\(([^,]+),\s*([^,]+),\s*'([^']+)',\s*(\d+)\)"

        def replace_datediff(match):
            date1_expr = match.group(1).strip()
            date2_expr = match.group(2).strip()
            unit = match.group(3)
            signed = int(match.group(4))

            date1_match = re.search(r'\[([^\]]+)\]', date1_expr)
            date2_match = re.search(r'\[([^\]]+)\]', date2_expr)

            if date1_match:
                date1_value = record.get(date1_match.group(1))
                date1_value = None if not date1_value else date1_value
            else:
                date1_value = date1_expr.strip("'\"")

            if date2_match:
                date2_value = record.get(date2_match.group(1))
                date2_value = None if not date2_value else date2_value
            else:
                date2_value = date2_expr.strip("'\"")

            if date1_value and date2_value:
                try:
                    result = self.calculate_datediff(str(date1_value), str(date2_value), unit, signed)
                    return str(result)
                except:
                    return "0"
            return "0"

        processed_logic = re.sub(datediff_pattern, replace_datediff, processed_logic)

        # If there's a None in a comparison, return False
        if re.search(r'None\s*[=<>!]+', processed_logic) and 'datediff' not in processed_logic:
            return False

        warnings.filterwarnings("ignore", category=SyntaxWarning)

        try:
            safe_globals = {
                '__builtins__': {},
                'True': True,
                'False': False,
                'None': None,
            }
            result = eval(processed_logic, safe_globals, {})
            return bool(result)
        except Exception:
            # For any evaluation error, return False
            return False


class ValidationEngine:
    """Main validation engine"""

    def __init__(self, schema: Dict[str, FieldSchema]):
        self.schema = schema
        self.evaluator = SafeEvaluator(schema)

    def _evaluate_branching_logic(self, logic: str, record: Dict[str, Any]) -> bool:
        return self.evaluator.evaluate(logic, record)

    def is_field_applicable(self, field_name: str, record: Dict[str, Any]) -> bool:
        schema = self.schema.get(field_name)
        if not schema or not schema.branching_logic:
            return True
        return self._evaluate_branching_logic(schema.branching_logic, record)

    def validate_record(self, record: Dict[str, Any], record_id: str = None) -> Dict[str, Any]:
        issues = []

        # Evaluate branching logic for all fields
        applicable_fields = {}
        for field_name, schema in self.schema.items():
            if self.is_field_applicable(field_name, record):
                applicable_fields[field_name] = schema

        # Validate applicable fields
        for field_name, value in record.items():
            schema = self.schema.get(field_name)
            if not schema:
                continue

            if not schema.is_required_for_qc:
                continue

            if field_name not in applicable_fields:
                continue

            # REQUIRED CHECK FIRST - even if value is empty
            if schema.required and (value is None or value == ''):
                issues.append({
                    'field_name': field_name,
                    'severity': 'error',
                    'rule_name': 'required',
                    'message': f"Required field '{field_name}' is empty",
                    'actual_value': value,
                })
                continue

            # Skip further validation for empty values (non-required fields)
            if not value:
                continue

            # Date validation
            if schema.is_date:
                is_valid, error_msg, _ = schema.validate_date_string(str(value))
                if not is_valid:
                    issues.append({
                        'field_name': field_name,
                        'severity': 'error',
                        'rule_name': 'date_format',
                        'message': f"Invalid date format: {error_msg}",
                        'actual_value': value,
                        'expected_value': schema.display_format_example,
                    })
                    continue

            # Time validation
            if schema.is_time:
                is_valid, error_msg, _ = schema.validate_time_string(str(value))
                if not is_valid:
                    issues.append({
                        'field_name': field_name,
                        'severity': 'error',
                        'rule_name': 'time_format',
                        'message': f"Invalid time format: {error_msg}",
                        'actual_value': value,
                        'expected_value': schema.display_format_example,
                    })
                    continue

            # Numeric validation
            if schema.is_numeric:
                try:
                    float(value)
                except ValueError:
                    issues.append({
                        'field_name': field_name,
                        'severity': 'error',
                        'rule_name': 'data_type',
                        'message': f"Expected numeric value, got '{value}'",
                        'actual_value': value,
                    })
                    continue

            # Range validation
            if schema.is_numeric and schema.has_range:
                try:
                    num = float(value)
                    if schema.min_value is not None and num < schema.min_value:
                        issues.append({
                            'field_name': field_name,
                            'severity': 'error',
                            'rule_name': 'range',
                            'message': f"Value {value} below minimum {schema.min_value}",
                            'actual_value': value,
                            'expected_value': f">= {schema.min_value}",
                        })
                    if schema.max_value is not None and num > schema.max_value:
                        issues.append({
                            'field_name': field_name,
                            'severity': 'error',
                            'rule_name': 'range',
                            'message': f"Value {value} exceeds maximum {schema.max_value}",
                            'actual_value': value,
                            'expected_value': f"<= {schema.max_value}",
                        })
                except:
                    pass

            # Choices validation
            if schema.has_choices and str(value) not in schema.choices:
                issues.append({
                    'field_name': field_name,
                    'severity': 'warning',
                    'rule_name': 'choice',
                    'message': f"Value '{value}' not in allowed choices",
                    'actual_value': value,
                    'expected_value': f"One of: {', '.join(list(schema.choices.keys())[:5])}",
                })

            # Email validation
            if schema.is_email:
                email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
                if not re.match(email_pattern, str(value)):
                    issues.append({
                        'field_name': field_name,
                        'severity': 'warning',
                        'rule_name': 'email_format',
                        'message': f"Invalid email format",
                        'actual_value': value,
                        'expected_value': 'user@example.com',
                    })

        return {
            'record_id': record_id,
            'is_valid': len([i for i in issues if i['severity'] == 'error']) == 0,
            'issues': issues,
            'error_count': len([i for i in issues if i['severity'] == 'error']),
            'warning_count': len([i for i in issues if i['severity'] == 'warning']),
        }

    def validate_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        results = []
        for record in records:
            record_id = record.get('record_id', 'unknown')
            results.append(self.validate_record(record, record_id))
        return results


class DictionaryLoader:
    """Load REDCap data dictionary"""

    @staticmethod
    def load(rows: List[Dict[str, Any]]) -> Dict[str, FieldSchema]:
        schema = {}

        for row in rows:
            field_name = row.get("Variable / Field Name", "").strip()
            if not field_name:
                continue

            validation_type = row.get("Text Validation Type", "")
            if validation_type and validation_type.startswith("text_"):
                validation_type = validation_type[5:]

            schema[field_name] = FieldSchema(
                field_name=field_name,
                form_name=row.get("Form Name"),
                field_label=row.get("Field Label"),
                field_type=row.get("Field Type", "unknown"),
                validation_type=validation_type,
                required=row.get("Required Field?", "").lower() in ["yes", "y", "1"],
                min_value=DictionaryLoader._to_float(row.get("Text Validation Min")),
                max_value=DictionaryLoader._to_float(row.get("Text Validation Max")),
                choices=DictionaryLoader._parse_choices(row.get("Choices, Calculations, OR Slider Labels")),
                branching_logic=row.get("Branching Logic (Show field only if...)"),
                is_pii=row.get("Identifier?", "").lower() in ["yes", "y", "1"],
                field_note=row.get("Field Note"),
                section_header=row.get("Section Header"),
                field_annotation=row.get("Field Annotation"),
            )

        return schema

    @staticmethod
    def _parse_choices(raw: Optional[str]) -> Optional[Dict[str, str]]:
        if not raw:
            return None
        choices = {}
        try:
            for part in raw.split("|"):
                if "," in part:
                    key, label = part.split(",", 1)
                    choices[key.strip()] = label.strip()
        except:
            pass
        return choices or None

    @staticmethod
    def _to_float(value: Optional[str]) -> Optional[float]:
        if not value:
            return None
        try:
            return float(value)
        except:
            return None