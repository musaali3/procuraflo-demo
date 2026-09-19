from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from fastapi import HTTPException

MONEY_QUANTUM = Decimal('0.01')
QUANTITY_QUANTUM = Decimal('0.000001')


def decimal_value(value, field='Value', *, positive=False, nonnegative=False):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise HTTPException(400, f'{field} must be numeric')
    if not result.is_finite() or (positive and result <= 0) or (nonnegative and result < 0):
        qualifier = 'greater than zero' if positive else 'zero or greater'
        raise HTTPException(400, f'{field} must be {qualifier}')
    return result


def money(value):
    return decimal_value(value).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def quantity(value):
    return decimal_value(value, 'Quantity', positive=True).quantize(QUANTITY_QUANTUM, rounding=ROUND_HALF_UP)


def uom_snapshot(item, transaction_quantity, transaction_uom=None, purpose='base', allow_zero=False):
    base_uom = str(item.get('uom') or '').strip().upper()
    default_uom = item.get('purchase_uom') if purpose == 'purchase' else item.get('issue_uom') if purpose == 'issue' else base_uom
    selected_uom = str(transaction_uom or default_uom or base_uom).strip().upper()
    allowed = {base_uom, str(default_uom or '').strip().upper()}
    if not base_uom or selected_uom not in allowed:
        raise HTTPException(400, f'{selected_uom or "Transaction UOM"} is not configured for this item')
    factor = Decimal('1') if selected_uom == base_uom else decimal_value(item.get('conversion_factor') or 0, 'UOM conversion factor', positive=True)
    transaction_qty = decimal_value(transaction_quantity, 'Quantity', nonnegative=True).quantize(QUANTITY_QUANTUM, rounding=ROUND_HALF_UP) if allow_zero else quantity(transaction_quantity)
    base_qty = (transaction_qty * factor).quantize(QUANTITY_QUANTUM, rounding=ROUND_HALF_UP)
    return {
        'transaction_quantity': transaction_qty,
        'transaction_uom': selected_uom,
        'conversion_factor_used': factor,
        'base_quantity': base_qty,
        'base_uom': base_uom,
    }


def convert_with_snapshot(transaction_quantity, transaction_uom, conversion_factor, base_uom):
    transaction_qty = quantity(transaction_quantity)
    factor = decimal_value(conversion_factor or 1, 'Historical UOM conversion factor', positive=True)
    return {
        'transaction_quantity': transaction_qty,
        'transaction_uom': str(transaction_uom or base_uom).upper(),
        'conversion_factor_used': factor,
        'base_quantity': (transaction_qty * factor).quantize(QUANTITY_QUANTUM, rounding=ROUND_HALF_UP),
        'base_uom': str(base_uom or transaction_uom).upper(),
    }


def po_line(line):
    qty = decimal_value(line.get('quantity'), 'Quantity', positive=True)
    price = decimal_value(line.get('price'), 'Unit price', nonnegative=True)
    discount = decimal_value(line.get('discount') or 0, 'Discount', nonnegative=True)
    freight = decimal_value(line.get('freight') or 0, 'Freight', nonnegative=True)
    other = decimal_value(line.get('other_charges') or 0, 'Other charges', nonnegative=True)
    tax_rate = decimal_value(line.get('tax') or 0, 'Tax', nonnegative=True)
    if tax_rate > 100:
        raise HTTPException(400, 'Tax percentage cannot exceed 100')
    line_amount = money(qty * price)
    tax_amount = money(line_amount * tax_rate / Decimal('100'))
    total = money(line_amount - discount + freight + other + tax_amount)
    if total < 0:
        raise HTTPException(400, 'Line discount cannot exceed the calculated line value and charges')
    return {**line, 'line_amount': line_amount, 'discount': money(discount), 'freight': money(freight),
            'other_charges': money(other), 'tax_amount': tax_amount, 'line_total': total}


def calculate_po(lines):
    calculated = [po_line(line) for line in lines]
    return {
        'lines': calculated,
        'subtotal': money(sum((line['line_amount'] for line in calculated), Decimal('0'))),
        'discount': money(sum((line['discount'] for line in calculated), Decimal('0'))),
        'freight': money(sum((line['freight'] for line in calculated), Decimal('0'))),
        'other_charges': money(sum((line['other_charges'] for line in calculated), Decimal('0'))),
        'tax': money(sum((line['tax_amount'] for line in calculated), Decimal('0'))),
        'grand_total': money(sum((line['line_total'] for line in calculated), Decimal('0'))),
    }


def base_unit_cost(transaction_unit_cost, conversion_factor):
    factor = decimal_value(conversion_factor, 'UOM conversion factor', positive=True)
    return money(decimal_value(transaction_unit_cost, 'Unit cost', nonnegative=True) / factor)


def inventory_value(base_quantity, inventory_unit_cost):
    return money(decimal_value(base_quantity) * decimal_value(inventory_unit_cost))
