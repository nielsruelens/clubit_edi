from openerp.osv import osv
from openerp.tools.translate import _


##############################################################################
#
#    clubit.tools.edi.wizard.outgong.desadv
#
#    Action handler class for delivery order outgoing (DESADV)
#
##############################################################################
class clubit_tools_edi_wizard_outgoing_desadv(osv.TransientModel):
    _inherit = ['clubit.tools.edi.wizard.outgoing']
    _name = 'clubit.tools.edi.wizard.outgoing.desadv'
    _description = 'Send DESADV'