from openerp.osv import osv
from openerp.tools.translate import _


##############################################################################
#
#    clubit.tools.edi.wizard.outgong.invoice
#
#    Action handler class for delivery order outgoing (normal)
#
##############################################################################
class clubit_tools_edi_wizard_outgoing_invoice(osv.TransientModel):
    _inherit = ['clubit.tools.edi.wizard.outgoing']
    _name = 'clubit.tools.edi.wizard.outgoing.invoice'
    _description = 'Send Invoices'