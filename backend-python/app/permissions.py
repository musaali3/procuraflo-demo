TASK_PERMISSIONS = ['task.pr','task.rfq','task.po','task.invoices','task.grn','task.material_issue','task.returns','task.transfers','task.adjustments','task.inventory','task.cycle_count','task.tools','task.vendor_scorecard','task.employees','task.suppliers','task.items','task.warehouses','task.settings','task.import_data','task.live_activity']
REPORT_PERMISSIONS = ['report.procurement','report.inventory','report.warehouse','report.employee','report.tools','report.system','report.executive']
ACTION_PERMISSIONS = ['po.view','po.create','po.edit','po.approve','po.reject','po.print','vendor.view','vendor.create','vendor.edit','vendor.disable','grn.view','grn.post','issue.view','issue.post','adjustment.view','adjustment.create','adjustment.approve']
ALL_PERMISSIONS = TASK_PERMISSIONS + REPORT_PERMISSIONS + ACTION_PERMISSIONS
ROLE_DEFAULTS = {
    'SupplyChainManager': ALL_PERMISSIONS,
    'PurchaseManager': ['task.pr','task.rfq','task.po','task.invoices','task.employees','task.suppliers','task.items','po.view','po.create','po.edit','po.approve','po.reject','po.print','vendor.view','vendor.create','vendor.edit','vendor.disable','report.procurement'],
    'PurchaseOfficer': ['task.pr','task.rfq','task.po','task.invoices','task.suppliers','task.items','po.view','po.create','po.edit','po.approve','po.reject','po.print','vendor.view','vendor.create','vendor.edit','report.procurement'],
    'WarehouseManager': ['task.pr','task.po','task.grn','task.material_issue','task.returns','task.transfers','task.adjustments','task.inventory','task.cycle_count','task.tools','task.employees','task.warehouses','po.view','grn.view','grn.post','issue.view','issue.post','adjustment.view','adjustment.create','adjustment.approve','report.inventory','report.warehouse','report.employee','report.tools'],
    'WarehouseSupervisor': ['task.pr','task.po','task.grn','task.material_issue','task.returns','task.transfers','task.adjustments','task.inventory','task.cycle_count','task.tools','task.warehouses','po.view','grn.view','grn.post','issue.view','issue.post','adjustment.view','adjustment.create','report.inventory','report.warehouse','report.employee','report.tools'],
    'Storekeeper': ['task.pr','task.po','task.grn','task.material_issue','task.returns','task.transfers','task.inventory','task.cycle_count','task.tools','po.view','grn.view','grn.post','issue.view','issue.post','report.inventory','report.warehouse','report.employee','report.tools'],
    'Helper': [],
}

def defaults_for_role(role):
    return list(ROLE_DEFAULTS.get(role, []))
