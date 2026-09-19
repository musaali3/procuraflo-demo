from decimal import Decimal

from app.calculations import base_unit_cost, calculate_po, inventory_value, uom_snapshot


def test_purchase_issue_and_fractional_uom_conversion_preserve_snapshot():
    item={'uom':'KG','purchase_uom':'TON','issue_uom':'BAG','conversion_factor':1000}
    purchase=uom_snapshot(item,2,purpose='purchase')
    fractional=uom_snapshot(item,'0.125',purpose='purchase')
    issue=uom_snapshot(item,'1.5',purpose='issue')
    assert purchase['base_quantity']==Decimal('2000.000000')
    assert fractional['base_quantity']==Decimal('125.000000')
    assert issue['base_quantity']==Decimal('1500.000000')
    item['conversion_factor']=500
    assert purchase['conversion_factor_used']==Decimal('1000')
    assert purchase['base_quantity']==Decimal('2000.000000')


def test_po_financials_are_decimal_rounded_and_include_all_components():
    result=calculate_po([{'quantity':'3','price':'10.005','discount':'1.00','freight':'2.00','other_charges':'0.50','tax':'15'}])
    line=result['lines'][0]
    assert line['line_amount']==Decimal('30.02')
    assert line['tax_amount']==Decimal('4.50')
    assert line['line_total']==Decimal('36.02')
    assert result['grand_total']==Decimal('36.02')


def test_grn_base_cost_and_accepted_value_exclude_rejected_quantity():
    cost=base_unit_cost('20000',1000)
    accepted=uom_snapshot({'uom':'KG','purchase_uom':'TON','conversion_factor':1000},'1.5',purpose='purchase')
    assert cost==Decimal('20.00')
    assert inventory_value(accepted['base_quantity'],cost)==Decimal('30000.00')
