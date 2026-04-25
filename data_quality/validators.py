from dataclasses import dataclass
from typing import Dict, Any, List, Optional
from datetime import datetime, date
import re
import operator


@dataclass
class FieldSchema:
    field_name: str
    field_type: str = "text"
    required: bool = False
    branching_logic: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    choices: Optional[Dict[str, str]] = None
    validation_type: Optional[str] = None

    @property
    def is_numeric(self):
        return self.field_type in ["integer", "number", "float"]

    @property
    def is_date(self):
        return self.field_type in ["date", "datetime", "datetime_seconds", "datetime_ymd"]

    @property
    def has_choices(self):
        return bool(self.choices)

    @property
    def is_system(self) -> bool:
        return self.field_name in {
            "record_id",
            "redcap_event_name",
            "redcap_repeat_instrument",
            "redcap_repeat_instance",
            "redcap_data_access_group",
            "user_name",
            "user_dag_name",
        }


class SafeEvaluator:
    """Safe evaluation of branching logic with date support"""

    # Supported operators
    OPERATORS = {
        '==': operator.eq,
        '!=': operator.ne,
        '<>': operator.ne,  # REDCap uses <> for not equal
        '>': operator.gt,
        '>=': operator.ge,
        '<': operator.lt,
        '<=': operator.le,
        'and': lambda x, y: x and y,
        'or': lambda x, y: x or y,
    }

    def __init__(self, schema: Dict[str, FieldSchema]):
        self.schema = schema

    def parse_date(self, date_str: str) -> Optional[float]:
        """Parse date string to timestamp for comparison"""
        if not date_str:
            return None

        # Remove quotes if present
        date_str = date_str.strip("'\"")

        # Common date formats in REDCap
        date_formats = [
            "%Y-%m-%d",  # 2024-01-15
            "%Y-%m-%d %H:%M:%S",  # 2024-01-15 14:30:00
            "%m/%d/%Y",  # 01/15/2024
            "%d/%m/%Y",  # 15/01/2024
            "%Y-%m-%dT%H:%M:%S",  # 2024-01-15T14:30:00
        ]

        for fmt in date_formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.timestamp()
            except ValueError:
                continue

        # Try date only
        try:
            dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
            return dt.timestamp()
        except:
            pass

        return None

    def calculate_datediff(self, date1: str, date2: str, unit: str, signed: int = 1) -> float:
        """
        Calculate difference between two dates (like REDCap's datediff)

        Args:
            date1: First date string
            date2: Second date string
            unit: 'd' (days), 'm' (months), 'y' (years), 'h' (hours), 'mi' (minutes)
            signed: 1 = return signed difference, 0 = return absolute difference
        """
        ts1 = self.parse_date(date1)
        ts2 = self.parse_date(date2)

        if ts1 is None or ts2 is None:
            return 0

        diff_seconds = ts1 - ts2
        diff_days = diff_seconds / 86400

        if unit == 'd':  # days
            diff = diff_days
        elif unit == 'm':  # months (approximate)
            diff = diff_days / 30.44
        elif unit == 'y':  # years (approximate)
            diff = diff_days / 365.25
        elif unit == 'h':  # hours
            diff = diff_seconds / 3600
        elif unit == 'mi':  # minutes
            diff = diff_seconds / 60
        else:
            diff = diff_days

        if signed == 0:
            diff = abs(diff)

        return diff

    def tokenize(self, expression: str) -> List[str]:
        """Tokenize the logic expression"""
        # Split on operators and parentheses while preserving them
        tokens = []
        current = ""

        i = 0
        while i < len(expression):
            char = expression[i]

            # Handle multi-character operators
            if i + 1 < len(expression) and expression[i:i + 2] in ['>=', '<=', '==', '!=', '<>']:
                if current.strip():
                    tokens.append(current.strip())
                    current = ""
                tokens.append(expression[i:i + 2])
                i += 2
                continue

            # Handle single-character operators and parentheses
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

            # Handle spaces as separators
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

        # Handle parentheses recursively
        while '(' in tokens:
            # Find matching parentheses
            open_idx = None
            close_idx = None

            for i, token in enumerate(tokens):
                if token == '(':
                    open_idx = i
                elif token == ')' and open_idx is not None:
                    close_idx = i
                    break

            if open_idx is not None and close_idx is not None:
                # Evaluate expression inside parentheses
                inner_tokens = tokens[open_idx + 1:close_idx]
                inner_result = self.parse_tokens(inner_tokens)

                # Replace parentheses and their content with result
                tokens = tokens[:open_idx] + [str(inner_result)] + tokens[close_idx + 1:]

        # Evaluate comparison operators (>, <, >=, <=, ==, !=, <>)
        for op in ['>=', '<=', '==', '!=', '<>', '>', '<']:
            while op in tokens:
                idx = tokens.index(op)
                left = self._evaluate_comparand(tokens[idx - 1])
                right = self._evaluate_comparand(tokens[idx + 1])

                result = self.OPERATORS[op](left, right)

                tokens = tokens[:idx - 1] + [str(result)] + tokens[idx + 2:]

        # Evaluate 'and' operators (left-associative)
        while 'and' in tokens:
            idx = tokens.index('and')
            left = self._parse_value(tokens[idx - 1])
            right = self._parse_value(tokens[idx + 1])

            result = left and right

            tokens = tokens[:idx - 1] + [str(result)] + tokens[idx + 2:]

        # Evaluate 'or' operators (left-associative)
        while 'or' in tokens:
            idx = tokens.index('or')
            left = self._parse_value(tokens[idx - 1])
            right = self._parse_value(tokens[idx + 1])

            result = left or right

            tokens = tokens[:idx - 1] + [str(result)] + tokens[idx + 2:]

        # Return final value
        if len(tokens) == 1:
            return self._parse_value(tokens[0])

        return None

    def _evaluate_comparand(self, token: str) -> Any:
        """Evaluate a value for comparison"""
        # Check if it's a datediff function
        if token.startswith('datediff('):
            return self._evaluate_datediff(token)

        return self._parse_value(token)

    def _evaluate_datediff(self, datediff_str: str) -> float:
        """Evaluate datediff function"""
        # Parse: datediff([date1], [date2], 'unit', signed)
        match = re.match(r'datediff\(([^,]+),\s*([^,]+),\s*\'([^\']+)\',\s*(\d+)\)', datediff_str)
        if not match:
            return 0

        date1_expr = match.group(1).strip()
        date2_expr = match.group(2).strip()
        unit = match.group(3)
        signed = int(match.group(4))

        # Extract field names or values
        date1 = self._extract_value(date1_expr)
        date2 = self._extract_value(date2_expr)

        return self.calculate_datediff(date1, date2, unit, signed)

    def _extract_value(self, expr: str) -> str:
        """Extract value from field reference or literal"""
        expr = expr.strip()

        # Check if it's a field reference [field_name]
        field_match = re.match(r'\[([^\]]+)\]', expr)
        if field_match:
            # This should be replaced with actual record value during evaluation
            # For now, return the field name as placeholder
            return f"__FIELD__{field_match.group(1)}"

        # Remove quotes
        return expr.strip("'\"")

    def _parse_value(self, token: str) -> Any:
        """Parse a token into its actual value"""
        token = token.strip()

        # Boolean values
        if token.lower() == 'true':
            return True
        if token.lower() == 'false':
            return False

        # None/Null
        if token.lower() in ['null', 'none']:
            return None

        # Numbers (including negative and decimal)
        try:
            # Check if it's a number (including negative)
            if re.match(r'^-?\d+(?:\.\d+)?$', token):
                if '.' in token:
                    return float(token)
                return int(token)
        except ValueError:
            pass

        # Date (check if it looks like a date or timestamp)
        if re.match(r'\d{4}-\d{2}-\d{2}', token) or re.match(r'\d{2}/\d{2}/\d{4}', token):
            timestamp = self.parse_date(token)
            if timestamp is not None:
                return timestamp

        # String (remove quotes if present)
        if (token.startswith("'") and token.endswith("'")) or (token.startswith('"') and token.endswith('"')):
            return token[1:-1]

        return token

    def evaluate(self, logic: str, record: Dict[str, Any]) -> bool:
        """Evaluate branching logic expression"""
        if not logic or not logic.strip():
            return True

        # Replace field references with actual values from record
        processed_logic = logic

        # FIRST: Convert date literals in the logic to timestamps
        date_literals = re.findall(r"['\"]([0-9]{4}-[0-9]{2}-[0-9]{2})['\"]", processed_logic)
        for date_literal in date_literals:
            timestamp = self.parse_date(date_literal)
            if timestamp is not None:
                processed_logic = processed_logic.replace(f"'{date_literal}'", str(timestamp))
                processed_logic = processed_logic.replace(f'"{date_literal}"', str(timestamp))

        # THEN: Find all field references [field_name]
        field_refs = re.findall(r'\[([^\]]+)\]', logic)

        for field_ref in field_refs:
            value = record.get(field_ref)
            schema = self.schema.get(field_ref)

            # Treat empty strings as None for date fields
            if value == "" and schema and schema.is_date:
                value_repr = "None"
            elif value is None:
                value_repr = "None"
            elif schema and schema.is_date:
                # For date fields, convert to timestamp
                timestamp = self.parse_date(str(value))
                if timestamp is not None:
                    value_repr = str(timestamp)
                else:
                    value_repr = "None"  # Invalid date becomes None
            elif schema and schema.is_numeric:
                # For numeric fields, convert to number (no quotes)
                try:
                    if value == "":
                        value_repr = "None"
                    else:
                        num_value = float(value)
                        if num_value.is_integer():
                            value_repr = str(int(num_value))
                        else:
                            value_repr = str(num_value)
                except (ValueError, TypeError):
                    value_repr = "None"
            elif isinstance(value, str):
                if value == "":
                    # Empty string - treat as None for comparison purposes
                    value_repr = "None"
                else:
                    # Try to convert to number if it looks like one
                    try:
                        float_val = float(value)
                        if float_val.is_integer():
                            value_repr = str(int(float_val))
                        else:
                            value_repr = str(float_val)
                    except (ValueError, TypeError):
                        # Not a number, keep as string with quotes
                        escaped_value = value.replace("'", "\\'")
                        value_repr = f"'{escaped_value}'"
            elif isinstance(value, (int, float)):
                value_repr = str(value)
            elif isinstance(value, bool):
                value_repr = str(value)
            else:
                value_repr = "None"

            processed_logic = processed_logic.replace(f'[{field_ref}]', value_repr)

        # Handle "is not null" and "is null" expressions (these become "is not None" and "is None")
        processed_logic = processed_logic.replace("is not null", "is not None")
        processed_logic = processed_logic.replace("is null", "is None")

        # Handle "in" operator
        processed_logic = re.sub(r'(\w+)\s+in\s+\(([^)]+)\)', r'\1 in (\2)', processed_logic)

        # Handle "=" operator (convert to "==" for Python)
        processed_logic = re.sub(r'(?<![<>!])=(?!=)', '==', processed_logic)

        # Handle datediff functions
        datediff_pattern = r"datediff\(([^,]+),\s*([^,]+),\s*'([^']+)',\s*(\d+)\)"

        def replace_datediff(match):
            date1_expr = match.group(1).strip()
            date2_expr = match.group(2).strip()
            unit = match.group(3)
            signed = int(match.group(4))

            # Extract values from field references
            date1_match = re.search(r'\[([^\]]+)\]', date1_expr)
            date2_match = re.search(r'\[([^\]]+)\]', date2_expr)

            if date1_match:
                date1_value = record.get(date1_match.group(1))
                # Handle empty string as None
                if date1_value == "":
                    date1_value = None
            else:
                date1_value = date1_expr.strip("'\"")

            if date2_match:
                date2_value = record.get(date2_match.group(1))
                if date2_value == "":
                    date2_value = None
            else:
                date2_value = date2_expr.strip("'\"")

            # Calculate datediff only if both dates are valid
            if date1_value and date2_value:
                try:
                    result = self.calculate_datediff(str(date1_value), str(date2_value), unit, signed)
                    return str(result)
                except:
                    return "0"
            return "0"

        processed_logic = re.sub(datediff_pattern, replace_datediff, processed_logic)

        # Suppress syntax warnings
        import warnings
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
        except Exception as e:
            print(f"Evaluation error: {e}")
            print(f"Logic: {processed_logic}")
            return True


class ValidationEngine:
    """Main validation engine"""

    def __init__(self, schema: Dict[str, FieldSchema]):
        self.schema = schema
        self.evaluator = SafeEvaluator(schema)

    def _evaluate_branching_logic(self, logic: str, record: Dict[str, Any]) -> bool:
        """Evaluate branching logic using SafeEvaluator"""
        return self.evaluator.evaluate(logic, record)

    def is_field_applicable(self, field_name: str, record: Dict[str, Any]) -> bool:
        """Check if field is applicable"""
        schema = self.schema.get(field_name)
        if not schema or not schema.branching_logic:
            return True
        return self._evaluate_branching_logic(schema.branching_logic, record)

    def validate_record(self, record: Dict[str, Any], record_id: str = None) -> Dict[str, Any]:
        """Validate a single record"""
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

            if schema.is_system:
                continue

            if field_name not in applicable_fields:
                continue

            # Required field check
            if schema.required and (value is None or value == ''):
                issues.append({
                    'field_name': field_name,
                    'severity': 'error',
                    'rule_name': 'required',
                    'message': f"Required field '{field_name}' is empty",
                    'actual_value': value,
                })
                continue

            if not value:
                continue

            # Data type check
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

            # Range check (numeric only)
            if schema.is_numeric:
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

            # Choices check
            if schema.has_choices and str(value) not in schema.choices:
                issues.append({
                    'field_name': field_name,
                    'severity': 'warning',
                    'rule_name': 'choice',
                    'message': f"Value '{value}' not in allowed choices",
                    'actual_value': value,
                    'expected_value': f"One of: {', '.join(list(schema.choices.keys())[:5])}",
                })

            # Email format check
            if schema.validation_type == 'email':
                if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', str(value)):
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
        """Validate multiple records"""
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

            schema[field_name] = FieldSchema(
                field_name=field_name,
                field_type=row.get("Field Type", "text"),
                required=row.get("Required Field?", "").lower() in ["yes", "y", "1"],
                min_value=DictionaryLoader._to_float(row.get("Text Validation Min")),
                max_value=DictionaryLoader._to_float(row.get("Text Validation Max")),
                validation_type=row.get("Text Validation Type"),
                choices=DictionaryLoader._parse_choices(row.get("Choices, Calculations, OR Slider Labels")),
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