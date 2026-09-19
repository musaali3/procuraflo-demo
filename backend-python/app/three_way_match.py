from decimal import Decimal

from .calculations import decimal_value, money, quantity


COMPONENT_CODES = {
    'quantity': 'EXCEEDS_QUANTITY_TOLERANCE', 'unit_price': 'EXCEEDS_PRICE_TOLERANCE',
    'line_value': 'EXCEEDS_LINE_VALUE_TOLERANCE', 'total_value': 'EXCEEDS_TOTAL_TOLERANCE',
    'tax': 'EXCEEDS_TAX_TOLERANCE', 'freight': 'EXCEEDS_FREIGHT_TOLERANCE',
    'other_charges': 'EXCEEDS_OTHER_CHARGE_TOLERANCE', 'rounding': 'EXCEEDS_ROUNDING_TOLERANCE',
}


def allowed_variance(reference, percentage=None, absolute=None):
    limits=[]
    if percentage is not None:limits.append(abs(decimal_value(reference))*decimal_value(percentage)/Decimal('100'))
    if absolute is not None:limits.append(decimal_value(absolute))
    return min(limits) if limits else Decimal('0')


def compare_component(name, expected, actual, rule=None, monetary=True):
    rule=rule or {};normalize=money if monetary else quantity
    expected_value=normalize(expected);actual_value=normalize(actual);difference=abs(actual_value-expected_value)
    allowed=allowed_variance(expected_value,rule.get('percentage_tolerance'),rule.get('absolute_tolerance'))
    return {'component':name,'expected':float(expected_value),'actual':float(actual_value),'difference':float(difference),'allowed_variance':float(allowed),'passed':difference<=allowed,'failure_code':None if difference<=allowed else COMPONENT_CODES[name]}


def classify(comparisons):
    failure=next((row['failure_code'] for row in comparisons if not row['passed']),None)
    if failure:return failure
    return 'MATCHED_WITHIN_TOLERANCE' if any(row['difference']>0 for row in comparisons) else 'MATCHED'
