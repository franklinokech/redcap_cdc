from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import re


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
        return self.field_type in ["integer", "number", "float"] # TODO Add check for

    @property
    def has_choices(self):
        return bool(self.choices)

    @property
    def is_system(self) -> bool:
        """REDCap system/internal fields"""
        return self.field_name in {
            "record_id",
            "redcap_event_name",
            "redcap_repeat_instrument",
            "redcap_repeat_instance",
            "redcap_data_access_group",
            "user_name",
            "user_dag_name",
        }


class ValidationEngine:
    """Main validation engine"""

    def __init__(self, schema: Dict[str, FieldSchema]):
        self.schema = schema

    def _evaluate_branching_logic(self, logic: str, record: Dict[str, Any]) -> bool:
        """Evaluate branching logic"""
        if not logic or logic.strip() == "":
            return True

        # Replace field references with actual values
        evaluated_logic = logic

        # Find all field references [field_name]
        field_refs = re.findall(r'\[([^\]]+)\]', logic)

        for field_ref in field_refs:
            value = record.get(field_ref)

            # Convert value to string representation for evaluation
            if value is None:
                value_repr = "None"
            elif isinstance(value, str):
                # Try to convert numeric strings to numbers
                try:
                    # Check if it's an integer
                    if value.isdigit():
                        value_repr = value  # Keep as bare number, no quotes
                    else:
                        # Try float
                        float_val = float(value)
                        value_repr = str(float_val)  # Bare number, no quotes
                except ValueError:
                    # Not a number, keep as string with quotes
                    value_repr = f"'{value}'"
            elif isinstance(value, bool):
                value_repr = str(value)
            elif isinstance(value, (int, float)):
                value_repr = str(value)  # Bare number, no quotes
            else:
                value_repr = f"'{str(value)}'"

            evaluated_logic = evaluated_logic.replace(f'[{field_ref}]', value_repr)

        # Safely evaluate the logic expression
        try:
            # Use a restricted evaluation environment
            safe_globals = {
                '__builtins__': {},
                'True': True,
                'False': False,
                'None': None,
            }

            result = eval(evaluated_logic, safe_globals, {})
            return bool(result)
        except Exception as e:
            print(f"Branching logic evaluation error: {e}")
            # If evaluation fails, assume the field should be visible/required
            return True

    def is_field_applicable(self, field_name: str, record: Dict[str, Any]) -> bool:
        """Check if field is applicable"""
        schema = self.schema.get(field_name)
        if not schema or not schema.branching_logic:
            return True
        return self._evaluate_branching_logic(schema.branching_logic, record)

    def validate_record(self, record: Dict[str, Any], record_id: str = None) -> Dict[str, Any]:
        """Validate a single record"""
        issues = []

        # First, evaluate branching logic for all fields
        applicable_fields = {}

        for field_name, schema in self.schema.items():
            if self.is_field_applicable(field_name, record):
                applicable_fields[field_name] = schema

        # Validate only applicable fields
        for field_name, value in record.items():
            schema = self.schema.get(field_name)
            if not schema:
                continue


            # skip system/calculated fields
            if schema.is_system:
                continue

            # Skip if field is not applicable based on branching logic
            if field_name not in applicable_fields:
                continue

            # required field check
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

            # Range check
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
            record_id = record.get('record_id', 'unknown') # TODO Use REDCapProject model record id field
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




