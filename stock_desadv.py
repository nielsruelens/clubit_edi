from openerp.osv import osv,fields
from openerp.addons.edi import EDIMixin
import datetime
import json
import copy
from openerp.tools.translate import _


"""
-------------------------------------------------------------------------------
    EDI Structures for the outgoing interface.
-------------------------------------------------------------------------------
"""

DESADV_LINE = {
    'lijnnummer': '',    #incrementing value
    'ean': '',           #stock.move:product_id -> product.product:ean13
    'aantal': '',        #stock.move:product_qty
}

DESADV_PARTY = {
    'qual': '',
    'gln': '',
}

DESADV = {
    'message': {
        'berichtdatum': '',      #system date/time
        'pakbonnummer': '',      #stock.picking.out:name
        'leverplandatum': '',    #stock.picking.out:min_date
        'klantreferentie': '',   #stock.picking.out:order_reference
        'partys': {'party':[]},            #partner details
        'cpss': {                #line items
            'cps': {
                'lines': {"line":[]},
            },
        },
    },
}








class stock_picking(osv.Model):
    _name = "stock.picking"
    _inherit = "stock.picking"


    ''' stock.picking:_function_edi_sent_desadv_get()
        ---------------------------------------------
        This method calculates the value of field edi_sent_desadv by
        looking at the database and checking for EDI docs
        on this delivery.
        ------------------------------------------------------------ '''
    def _function_desadv_sent_get(self, cr, uid, ids, field, arg, context=None):
        edi_db = self.pool.get('clubit.tools.edi.document.outgoing')
        flow_db = self.pool.get('clubit.tools.edi.flow')
        flow_id = flow_db.search(cr, uid, [('model', '=', 'stock.picking.out'),('method', '=', 'send_desadv_out')])[0]
        res = dict.fromkeys(ids, False)
        for pick in self.browse(cr, uid, ids, context=context):
            docids = edi_db.search(cr, uid, [('flow_id', '=', flow_id),('reference', '=', pick.name)])
            if not docids: continue
            edi_docs = edi_db.browse(cr, uid, docids, context=context)
            edi_docs.sort(key = lambda x: x.create_date, reverse=True)
            res[pick.id] = edi_docs[0].create_date
        return res



    _columns = {
        'desadv_sent': fields.function(_function_desadv_sent_get, type='datetime', string='DESADV sent'),
    }








"""
-------------------------------------------------------------------------------
    Redefinition of stock.picking.out for outgoing EDI.
-------------------------------------------------------------------------------
"""
class stock_picking_out(osv.Model, EDIMixin):
    _name = "stock.picking.out"
    _inherit = "stock.picking.out"

    _directory_out_brico  = "EDI/to_brico/shipments/incoming/"
    _directory_out_praxis = "EDI/to_praxis/shipments/incoming/"



    ''' stock.picking.out:_function_edi_sent_desadv_get()
        -------------------------------------------------
        ATTENTION: The reason this method is declared twice,
        here and in the superclass is because inheritance is
        BROKEN FOR STOCK.PICKING & STOCK.PICKING.IN/OUT
        ----------------------------------------------------- '''
    def _function_desadv_sent_get(self, cr, uid, ids, field, arg, context=None):
        return False

    _columns = {
        'desadv_sent': fields.function(_function_desadv_sent_get, type='datetime', string='EDI sent'),
    }





    ''' stock.picking.out:send_desadv_out()
        -----------------------------------
        This method will perform the export of a delivery
        order, the DESADV version. Only deliveries that
        are in state 'done' may be passed to this method,
        otherwise an error will occur.
        ------------------------------------------------- '''
    def send_desadv_out(self, cr, uid, items, context=None):


        edi_db = self.pool.get('clubit.tools.edi.document.outgoing')

        # Get the selected items
        # ----------------------
        pickings = [x['id'] for x in items]
        pickings = self.browse(cr, uid, pickings, context=context)


        # Loop over all pickings to check if their
        # collective states allow for EDI processing
        # ------------------------------------------
        nope = ""
        for pick in pickings:
            if pick.state != 'done':
                nope += pick.name + ', '
        if nope:
            raise osv.except_osv(_('Warning!'), _("Not all documents had states 'assigned' or 'confirmed'. Please exclude the following documents: {!s}").format(nope))


        # Actual processing of all the deliveries
        # ---------------------------------------
        for pick in pickings:
            content = self.edi_export_desadv(cr, uid, pick, None, context)
            partner_id = [x['partner_id'] for x in items if x['id'] == pick.id][0]
            result = edi_db.create_from_content(cr, uid, pick.name, content, partner_id, 'stock.picking.out', 'send_desadv_out')
            if result != True:
                raise osv.except_osv(_('Error!'), _("Something went wrong while trying to create one of the EDI documents. Please contact your system administrator. Error given: {!s}").format(result))





    ''' stock.picking.out:desadv_partner_resolver()
        -------------------------------------------
        This method attempts to find the correct partner
        to whom we should send an DESADV document for a
        number of deliveries.
        ------------------------------------------------ '''
    def desadv_partner_resolver(self, cr, uid, ids, context):

        order_db   = self.pool.get('sale.order')
        result_list = []
        for pick in self.browse(cr, uid, ids, context):
            so_id = order_db.search(cr, uid,[('name', '=', pick.origin)])
            if not so_id:
                raise osv.except_osv(_('Warning!'), _("Could not find matching sales order for an item in your selection!"))
            order = order_db.browse(cr, uid, so_id, context)[0]
            result_list.append({'id' : pick.id, 'partner_id': order.partner_id.id})
        return result_list




    def edi_export_desadv(self, cr, uid, delivery, edi_struct=None, context=None):
        """This method creates an EDI dictionary of an delivery.
           The output dict is so radically different from a standard
           EDI document that we have to write a complete custom method.

           Args:
               invoice: the actual object to be processed.

           Returns:
               edi_doc: EDI invoice.
        """

        # Instantiate variables
        # ---------------------
        edi_doc = copy.deepcopy(dict(DESADV))

        partner_db = self.pool.get('res.partner')
        order_db   = self.pool.get('sale.order')
        company_db = self.pool.get('res.company')
        product_db = self.pool.get('product.product')


        co_id  = company_db.search(cr, uid, [])[0]
        so_id = order_db.search(cr, uid,[('name', '=', delivery.origin)])
        if not so_id:
            raise osv.except_osv(_('Warning!'), _("Could not find matching sales order for an item in your selection!"))


        order = order_db.browse(cr, uid, so_id, context)[0]
        company  = company_db.browse(cr, uid, co_id, context)
        now = datetime.datetime.now()



        # Basic header fields
        # -------------------
        d = datetime.datetime.strptime(delivery.min_date, "%Y-%m-%d %H:%M:%S")

        edi_doc['message']['pakbonnummer']     = delivery.name
        edi_doc['message']['leverplandatum']   = d.strftime("%Y%m%d%H%M%S")
        edi_doc['message']['berichtdatum']     = now.strftime("%Y%m%d%H%M%S")
        edi_doc['message']['klantreferentie']  = delivery.order_reference



        # Partner details
        # ---------------
        partner = partner_db.browse(cr, uid, order.partner_id.id, context)
        if partner and partner.ref:
            partner_doc = copy.deepcopy(dict(DESADV_PARTY))
            partner_doc['qual'] = 'BY'
            partner_doc['gln']  = partner.ref
            edi_doc['message']['partys']['party'].append(partner_doc)


        if company:
            partner = partner_db.browse(cr, uid, company.partner_id.id, context)
            if partner and partner.ref:
                partner_doc = copy.deepcopy(dict(DESADV_PARTY))
                partner_doc['qual'] = 'SU'
                partner_doc['gln']  = partner.ref
                edi_doc['message']['partys']['party'].append(partner_doc)


        partner = partner_db.browse(cr, uid, delivery.partner_id.id, context)
        if partner and partner.ref:
            partner_doc = copy.deepcopy(dict(DESADV_PARTY))
            partner_doc['qual'] = 'DP'
            partner_doc['gln']  = partner.ref
            edi_doc['message']['partys']['party'].append(partner_doc)



        # Line items
        # ----------
        line_counter = 1
        for line in delivery.move_lines:
            product = product_db.browse(cr, uid, line.product_id.id, context)
            edi_line = copy.deepcopy(dict(DESADV_LINE))
            edi_line['lijnnummer'] = line_counter
            edi_line['ean']        = product.ean13
            edi_line['aantal']     = int(line.product_qty)

            line_counter = line_counter + 1
            edi_doc['message']['cpss']['cps']['lines']['line'].append(edi_line)



        # Return the result
        # -----------------
        return edi_doc
















