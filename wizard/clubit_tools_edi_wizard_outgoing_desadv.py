from openerp.osv import osv, fields
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

    _columns = {
        'desadv_name': fields.char('DESADV name', size=64),
    }

    def select(self, cr, uid, ids, context=None):
        wizard = self.browse(cr, uid, ids, context)[0]
        pick_ids = context.get('active_ids', [])
        if wizard.desadv_name:
            self.pool.get('stock.picking.out').write(cr, uid, pick_ids, {'desadv_name':wizard.desadv_name}, context=context)
        return super(clubit_tools_edi_wizard_outgoing_desadv, self).select(cr, uid, ids, context=context)

    def resolve(self, cr, uid, ids, context=None):
        wizard = self.browse(cr, uid, ids, context)[0]
        pick_ids = context.get('active_ids', [])
        if wizard.desadv_name:
            self.update_desadv_name(cr, uid, ids, wizard.desadv_name, context)
            self.pool.get('stock.picking.out').write(cr, uid, pick_ids, {'desadv_name':wizard.desadv_name}, context=context)
        return super(clubit_tools_edi_wizard_outgoing_desadv, self).resolve(cr, uid, ids, context=context)

