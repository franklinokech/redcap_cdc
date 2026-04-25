from dataclasses import dataclass
from typing import Dict, Any, List, Optional


# =====================================================
# SCHEMA MODEL
# =====================================================

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
        """
        Determines if this field should be validated
        """
        return not (
            self.is_system
            or self.is_calculated
        )

    @property
    def is_numeric(self) -> bool:
        return (
            self.field_type in {"integer", "number", "float"}
            or self.validation_type in {"integer", "number", "float"}
        )

    @property
    def has_choices(self) -> bool:
        return bool(self.choices)

    @property
    def has_range(self) -> bool:
        return self.min_value is not None or self.max_value is not None


# =====================================================
# LOADER
# =====================================================

class REDCapDictionaryLoader:
    """
    Converts REDCap Data Dictionary rows into structured schema.
    Robust against:
    - BOM encoding issues
    - Quoted headers
    - Case differences
    """

    # normalized column names (lowercase, no quotes, stripped)
    COL = {
        "field_name": "variable / field name",
        "form_name": "form name",
        "section_header": "section header",
        "field_type": "field type",
        "field_label": "field label",
        "choices": "choices, calculations, or slider labels",
        "field_note": "field note",
        "validation_type": "text validation type or show slider number",
        "min": "text validation min",
        "max": "text validation max",
        "identifier": "identifier?",
        "branching_logic": "branching logic (show field only if...)",
        "required": "required field?",
        "field_annotation": "field annotation",
    }

    def __init__(self, rows: List[Dict[str, Any]]):
        self.rows = [self._normalize_row(r) for r in rows if any(r.values())]

    # -------------------------------------------------
    # PUBLIC API
    # -------------------------------------------------

    def load(self) -> Dict[str, FieldSchema]:
        schema: Dict[str, FieldSchema] = {}

        for row in self.rows:
            field = self._parse_row(row)

            if not field.field_name:
                # Debug safety (can remove later)
                # print("⚠️ Skipping row with no field_name:", row)
                continue

            schema[field.field_name] = field

        return schema

    # -------------------------------------------------
    # NORMALIZATION
    # -------------------------------------------------

    def _clean_key(self, key: str) -> str:
        return key.strip().strip('"').lower()

    def _normalize_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            self._clean_key(k): v
            for k, v in row.items()
        }

    # -------------------------------------------------
    # CORE PARSER
    # -------------------------------------------------

    def _parse_row(self, row: Dict[str, Any]) -> FieldSchema:
        return FieldSchema(
            field_name=self._get(row, "field_name"),
            form_name=self._get(row, "form_name"),
            field_label=self._get(row, "field_label"),

            field_type=self._get(row, "field_type") or "unknown",
            validation_type=self._get(row, "validation_type"),

            required=self._is_yes(row, "required"),
            is_pii=self._is_yes(row, "identifier"),

            min_value=self._to_float(self._get(row, "min")),
            max_value=self._to_float(self._get(row, "max")),

            choices=self._parse_choices(self._get(row, "choices")),

            branching_logic=self._get(row, "branching_logic"),

            field_note=self._get(row, "field_note"),
            section_header=self._get(row, "section_header"),
            field_annotation=self._get(row, "field_annotation"),
        )

    # -------------------------------------------------
    # HELPERS
    # -------------------------------------------------

    def _get(self, row: Dict[str, Any], key: str) -> Optional[str]:
        col = self.COL.get(key)
        if not col:
            return None

        value = row.get(col)
        if value is None:
            return None

        value = str(value).strip()
        return value or None

    def _is_yes(self, row: Dict[str, Any], key: str) -> bool:
        value = self._get(row, key)
        return str(value).lower() in {"yes", "y", "true", "1"}

    def _to_float(self, value: Optional[str]) -> Optional[float]:
        if value in (None, "", "NA"):
            return None
        try:
            return float(value)
        except ValueError:
            return None

    # -------------------------------------------------
    # CHOICES PARSER
    # -------------------------------------------------

    def _parse_choices(self, raw: Optional[str]) -> Optional[Dict[str, str]]:
        """
        Parses REDCap choice strings like:
        "1, Male | 2, Female | 3, Other"
        """
        if not raw:
            return None

        choices: Dict[str, str] = {}

        try:
            parts = raw.split("|")
            for part in parts:
                if "," in part:
                    key, label = part.split(",", 1)
                    choices[key.strip()] = label.strip()
        except Exception:
            return None

        return choices or None