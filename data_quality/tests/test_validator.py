# test_validator_property.py
import pytest
from datetime import datetime, timedelta
from hypothesis import given, strategies as st, settings, HealthCheck
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant
from faker import Faker
from data_quality.validators import ValidationEngine, FieldSchema

# Faker only for non-Hypothesis tests
fake = Faker()

# Complex schema as constant
COMPLEX_SCHEMA = {
    "record_id": FieldSchema(
        field_name="record_id",
        field_type="text",
        required=True
    ),
    "age": FieldSchema(
        field_name="age",
        field_type="integer",
        required=True,
        min_value=0,
        max_value=120
    ),
    "gender": FieldSchema(
        field_name="gender",
        field_type="text",
        required=True,
        choices={"1": "Male", "2": "Female", "3": "Other"}
    ),
    "enrollment_date": FieldSchema(
        field_name="enrollment_date",
        field_type="date",
        required=True
    ),
    "surgery_date": FieldSchema(
        field_name="surgery_date",
        field_type="date"
    ),
    "followup_date": FieldSchema(
        field_name="followup_date",
        field_type="date"
    ),
    "pregnancy_status": FieldSchema(
        field_name="pregnancy_status",
        field_type="text",
        choices={"0": "No", "1": "Yes", "2": "Unknown"}
    ),
    "diabetes_status": FieldSchema(
        field_name="diabetes_status",
        field_type="text",
        choices={"0": "No", "1": "Type 1", "2": "Type 2"}
    ),
    "treatment_arm": FieldSchema(
        field_name="treatment_arm",
        field_type="text",
        choices={"A": "Arm A", "B": "Arm B", "C": "Arm C"}
    ),
    "pregnancy_details": FieldSchema(
        field_name="pregnancy_details",
        field_type="text",
        required=True,
        branching_logic="[pregnancy_status] = '1'"
    ),
    "gestational_age": FieldSchema(
        field_name="gestational_age",
        field_type="integer",
        required=True,
        min_value=0,
        max_value=42,
        branching_logic="[pregnancy_status] = '1' and [pregnancy_details] != ''"
    ),
    "geriatric_assessment": FieldSchema(
        field_name="geriatric_assessment",
        field_type="text",
        required=True,
        branching_logic="[age] >= 65"
    ),
    "female_only_questions": FieldSchema(
        field_name="female_only_questions",
        field_type="text",
        required=True,
        branching_logic="[gender] = '2'"
    ),
    "post_surgery_followup": FieldSchema(
        field_name="post_surgery_followup",
        field_type="text",
        required=True,
        branching_logic="[surgery_date] is not null and [surgery_date] >= '2024-01-01'"
    ),
    "complicated_followup": FieldSchema(
        field_name="complicated_followup",
        field_type="text",
        required=True,
        branching_logic="([age] > 60 and [diabetes_status] != '0') or ([treatment_arm] = 'B' and datediff([followup_date], [enrollment_date], 'd', 1) > 30)"
    ),
    "emergency_contact": FieldSchema(
        field_name="emergency_contact",
        field_type="text",
        required=True,
        branching_logic="[age] < 18 or [age] > 75 or [diabetes_status] in ('1', '2')"
    ),
    "research_consent_version": FieldSchema(
        field_name="research_consent_version",
        field_type="text",
        required=True,
        branching_logic="[enrollment_date] >= '2024-06-01' and [enrollment_date] <= '2024-12-31'"
    ),
    "extended_followup": FieldSchema(
        field_name="extended_followup",
        field_type="text",
        required=True,
        branching_logic="([treatment_arm] = 'A' or [treatment_arm] = 'B') and [age] <= 50 and datediff([followup_date], [surgery_date], 'd', 1) >= 90"
    ),
    "safety_form": FieldSchema(
        field_name="safety_form",
        field_type="text",
        required=True,
        branching_logic="([age] >= 65 and [diabetes_status] != '0') or ([pregnancy_status] = '1' and datediff([followup_date], [enrollment_date], 'd', 1) <= 180) or [treatment_arm] = 'C'"
    )
}


# =====================================================
# SIMPLIFIED HYPOTHESIS STRATEGIES
# =====================================================

@st.composite
def simple_date(draw):
    """Simple date strategy - reduced complexity"""
    year = draw(st.integers(min_value=2020, max_value=2025))
    month = draw(st.integers(min_value=1, max_value=12))
    day = draw(st.integers(min_value=1, max_value=28))  # Simplified to avoid invalid dates
    return f"{year}-{month:02d}-{day:02d}"


@st.composite
def simple_record(draw):
    """Simplified record strategy - much smaller and faster"""

    # Required fields only
    record_id = draw(st.one_of(
        st.just("TEST001"),
        st.just(""),
        st.text(min_size=1, max_size=5, alphabet=st.characters(whitelist_categories=('L', 'N')))
    ))

    age = draw(st.one_of(
        st.just("30"),  # Common value
        st.just("65"),  # Boundary
        st.just("0"),  # Min
        st.just("120"),  # Max
        st.integers(min_value=0, max_value=120).map(str),  # Random valid
        st.just("150"),  # Invalid high
        st.just("-5")  # Invalid negative
    ))

    gender = draw(st.sampled_from(["1", "2", "3", "99"]))  # 99 is invalid
    enrollment_date = draw(st.one_of(
        st.just("2024-01-01"),
        st.just("2024-06-15"),
        st.just("2024-12-31"),
        simple_date()
    ))

    # Optional with defaults
    pregnancy_status = draw(st.sampled_from(["0", "1", "2"]))
    diabetes_status = draw(st.sampled_from(["0", "1", "2"]))
    treatment_arm = draw(st.sampled_from(["A", "B", "C", "X"]))  # X is invalid

    # Conditional fields - simplified
    pregnancy_details = ""
    geriatric_assessment = ""
    female_only_questions = ""

    if pregnancy_status == "1":
        pregnancy_details = draw(st.one_of(
            st.just("First trimester"),
            st.just(""),
            st.text(min_size=1, max_size=20)
        ))

    try:
        age_int = int(age) if age.isdigit() else 0
        if age_int >= 65:
            geriatric_assessment = draw(st.one_of(
                st.just("Needs assessment"),
                st.just("")
            ))
    except:
        pass

    if gender == "2":
        female_only_questions = draw(st.one_of(
            st.just("Female-specific question"),
            st.just("")
        ))

    return {
        "record_id": record_id,
        "age": age,
        "gender": gender,
        "enrollment_date": enrollment_date,
        "surgery_date": draw(st.one_of(st.just(""), simple_date())),
        "followup_date": draw(st.one_of(st.just(""), simple_date())),
        "pregnancy_status": pregnancy_status,
        "diabetes_status": diabetes_status,
        "treatment_arm": treatment_arm,
        "pregnancy_details": pregnancy_details,
        "gestational_age": draw(st.one_of(st.just(""), st.just("12"), st.integers(min_value=0, max_value=42).map(str))),
        "geriatric_assessment": geriatric_assessment,
        "female_only_questions": female_only_questions,
        "post_surgery_followup": draw(st.one_of(st.just(""), st.just("Followup needed"))),
        "complicated_followup": draw(st.one_of(st.just(""), st.just("Complicated"))),
        "emergency_contact": draw(st.one_of(st.just(""), st.just("555-1234"))),
        "research_consent_version": draw(st.one_of(st.just(""), st.just("v1.0"))),
        "extended_followup": draw(st.one_of(st.just(""), st.just("Extended"))),
        "safety_form": draw(st.one_of(st.just(""), st.just("Safety required")))
    }


# =====================================================
# PROPERTY-BASED TESTS WITH HEALTH CHECK DISABLED
# =====================================================

class TestRedcapPropertyBased:
    """Property-based tests using simplified Hypothesis strategies"""

    @given(record=simple_record())
    @settings(suppress_health_check=[HealthCheck.large_base_example], max_examples=50)
    def test_property_no_crash_on_any_record(self, record):
        """PROPERTY: Validator should never crash on any record"""
        engine = ValidationEngine(COMPLEX_SCHEMA)

        try:
            result = engine.validate_record(record)
            assert 'is_valid' in result
            assert 'error_count' in result
            assert 'warning_count' in result
        except Exception as e:
            pytest.fail(f"Property violated: Validator crashed on {record}: {e}")

    @given(age=st.integers(min_value=-50, max_value=200))
    def test_property_age_range(self, age):
        """PROPERTY: Age must be between 0 and 120 inclusive"""
        engine = ValidationEngine(COMPLEX_SCHEMA)
        record = {
            "record_id": "TEST001",
            "age": str(age),
            "gender": "1",
            "enrollment_date": "2024-01-01"
        }

        result = engine.validate_record(record)

        if 0 <= age <= 120:
            age_errors = [i for i in result['issues'] if i['field_name'] == 'age']
            assert len(age_errors) == 0, f"Valid age {age} caused error"

    @given(pregnant=st.booleans())
    def test_property_pregnancy_branching(self, pregnant):
        """PROPERTY: Pregnancy details required IFF pregnant"""
        engine = ValidationEngine(COMPLEX_SCHEMA)

        record = {
            "record_id": "TEST001",
            "age": "30",
            "gender": "2",
            "enrollment_date": "2024-01-01",
            "pregnancy_status": "1" if pregnant else "0",
            "pregnancy_details": ""
        }

        is_applicable = engine.is_field_applicable("pregnancy_details", record)

        assert is_applicable == pregnant, f"Applicable={is_applicable}, Pregnant={pregnant}"

    @given(gender=st.sampled_from(["1", "2", "3"]))
    def test_property_gender_branching(self, gender):
        """PROPERTY: Female-only questions required only for females"""
        engine = ValidationEngine(COMPLEX_SCHEMA)

        record = {
            "record_id": "TEST001",
            "age": "30",
            "gender": gender,
            "enrollment_date": "2024-01-01",
            "female_only_questions": ""
        }

        is_applicable = engine.is_field_applicable("female_only_questions", record)

        assert is_applicable == (gender == "2"), f"Gender={gender}, Applicable={is_applicable}"

    @given(age=st.integers(min_value=0, max_value=100))
    def test_property_geriatric_branching(self, age):
        """PROPERTY: Geriatric assessment required for age >= 65"""
        engine = ValidationEngine(COMPLEX_SCHEMA)

        record = {
            "record_id": "TEST001",
            "age": str(age),
            "gender": "1",
            "enrollment_date": "2024-01-01",
            "geriatric_assessment": ""
        }

        is_applicable = engine.is_field_applicable("geriatric_assessment", record)

        assert is_applicable == (age >= 65), f"Age={age}, Applicable={is_applicable}"

    @given(value=st.one_of(st.integers(), st.floats(), st.text(max_size=10), st.none()))
    def test_property_no_crash_on_invalid_input(self, value):
        """PROPERTY: Validator should never crash on any input type"""
        engine = ValidationEngine(COMPLEX_SCHEMA)
        record = {"some_field": value}

        try:
            result = engine.validate_record(record)
            assert 'is_valid' in result
        except Exception as e:
            pytest.fail(f"Property violated: Validator crashed with {value}: {e}")

    @given(treatment_arm=st.text(max_size=5))
    def test_property_choice_validation(self, treatment_arm):
        """PROPERTY: Choice validation should handle any input"""
        engine = ValidationEngine(COMPLEX_SCHEMA)

        record = {
            "record_id": "TEST001",
            "age": "50",
            "gender": "1",
            "enrollment_date": "2024-01-01",
            "treatment_arm": treatment_arm
        }

        try:
            result = engine.validate_record(record)
            assert 'is_valid' in result
        except Exception as e:
            pytest.fail(f"Property violated: Validator crashed: {e}")


# =====================================================
# STATE-BASED TESTING
# =====================================================

class RedcapStateMachine(RuleBasedStateMachine):
    """State machine for testing state transitions"""

    def __init__(self):
        super().__init__()
        self.engine = ValidationEngine(COMPLEX_SCHEMA)
        self.record = {
            "record_id": "STATE001",
            "enrollment_date": "2024-01-01"
        }

    @rule(age=st.integers(min_value=0, max_value=100))
    def set_age(self, age):
        self.record["age"] = str(age)

    @rule(pregnancy_status=st.sampled_from(["0", "1", "2"]))
    def set_pregnancy_status(self, pregnancy_status):
        self.record["pregnancy_status"] = pregnancy_status

        is_pregnant = pregnancy_status == "1"
        details_applicable = self.engine.is_field_applicable("pregnancy_details", self.record)

        assert details_applicable == is_pregnant

    @rule(pregnancy_details=st.text(max_size=20))
    def set_pregnancy_details(self, pregnancy_details):
        self.record["pregnancy_details"] = pregnancy_details

    @invariant()
    def no_crash(self):
        try:
            result = self.engine.validate_record(self.record)
            assert isinstance(result, dict)
        except Exception as e:
            raise AssertionError(f"Validator crashed: {e}")


# =====================================================
# BULK TESTING WITH FAKER (Separate from Hypothesis)
# =====================================================

def test_bulk_realistic_data():
    """Test with realistic Faker data (non-Hypothesis)"""
    engine = ValidationEngine(COMPLEX_SCHEMA)
    records = []

    for i in range(50):
        record = {
            "record_id": fake.uuid4(),
            "age": str(fake.random_int(0, 120)),
            "gender": str(fake.random_int(1, 3)),
            "enrollment_date": fake.date_between(start_date='-2y', end_date='+1y').strftime("%Y-%m-%d"),
            "pregnancy_status": str(fake.random_int(0, 2)),
            "diabetes_status": str(fake.random_int(0, 2)),
            "treatment_arm": fake.random_element(elements=["A", "B", "C"])
        }

        if record["pregnancy_status"] == "1":
            record["pregnancy_details"] = fake.sentence()

        if int(record["age"]) >= 65:
            record["geriatric_assessment"] = fake.sentence()

        if record["gender"] == "2":
            record["female_only_questions"] = fake.sentence()

        records.append(record)

    results = engine.validate_records(records)
    valid_count = sum(1 for r in results if r['is_valid'])

    print(f"\nBulk realistic data test: {valid_count}/50 valid records")
    assert len(results) == 50


def test_edge_cases():
    """Test known edge cases"""
    engine = ValidationEngine(COMPLEX_SCHEMA)

    edge_records = [
        {"record_id": "", "age": "30", "gender": "1", "enrollment_date": "2024-01-01"},
        {"record_id": "TEST", "age": "999", "gender": "1", "enrollment_date": "2024-01-01"},
        {"record_id": "TEST", "age": "30", "gender": "1", "enrollment_date": "invalid-date"},
        {"record_id": "TEST", "age": "30", "gender": "99", "enrollment_date": "2024-01-01"},
        {"record_id": "TEST", "age": "30", "gender": "1", "enrollment_date": "2024-01-01", "pregnancy_status": "1"},
        {"record_id": "TEST", "age": "65", "gender": "1", "enrollment_date": "2024-01-01"},
        {"record_id": "TEST", "age": "17", "gender": "1", "enrollment_date": "2024-01-01"},
    ]

    for i, record in enumerate(edge_records):
        result = engine.validate_record(record)
        assert 'is_valid' in result
        print(f"Edge case {i + 1}: valid={result['is_valid']}, errors={result['error_count']}")


# =====================================================
# Run state machine test
# =====================================================

TestRedcapStateMachine = RedcapStateMachine.TestCase

# =====================================================
# Run tests
# =====================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-s"])