from openerp.osv import osv
from openerp.addons.edi import EDIMixin
import datetime
import json
import copy
import shutil
from os import listdir
from os.path import isfile, join
from openerp.tools.translate import _


##############################################################################
#
#    sale.order
#
#    This class extends sale.order to allow for EDI processing.
#
##############################################################################
class sale_order(osv.Model, EDIMixin):
    _name = "sale.order"
    _inherit = "sale.order"


    ''' sale.order:edi_import_validator()
        --------------------------------------------
        This method will perform a validation on the provided
        EDI Document on a logical & functional level.
        ----------------------------------------------------- '''
    def edi_import_validator(self, cr, uid, ids, context):

        # Read the EDI Document
        # ---------------------
        edi_db = self.pool.get('clubit.tools.edi.document.incoming')
        document = edi_db.browse(cr, uid, ids, context)

        # Convert the document to JSON
        # ----------------------------
        try:
            data = json.loads(document.content)
            if not data:
                edi_db.message_post(cr, uid, document.id, body='Error found: EDI Document is empty.')
                return False
        except Exception:
            edi_db.message_post(cr, uid, document.id, body='Error found: content is not valid JSON.')
            return False



        # Does this document have the correct root name?
        # ----------------------------------------------
        if not 'message' in data:
            edi_db.message_post(cr, uid, document.id, body='Error found: could not find field: message.')
            return False
        data = data['message']


        # Validate the document reference
        # -------------------------------
        if not 'docnum' in data:
            edi_db.message_post(cr, uid, document.id, body='Error found: could not find field: docnum.')
            return False


        # Validate the sender
        # -------------------
        if not 'sender' in data:
            edi_db.message_post(cr, uid, document.id, body='Error found: could not find field: sender.')
            return False



        # Validate all the partners
        # -------------------------
        found_by = False
        found_dp = False
        found_iv = False
        if not 'partys' in data:
            edi_db.message_post(cr, uid, document.id, body='Error found: could not find field: partys.')
            return False
        try:
            data['partys'] = data['partys'][0]['party']
        except Exception:
            edi_db.message_post(cr, uid, document.id, body='Error found: erroneous structure for table: partys.')
            return False
        if len(data['partys']) == 0:
            edi_db.message_post(cr, uid, document.id, body='Error found: content of table partys is empty. ')
            return False

        partner_db = self.pool.get('res.partner')
        for party in data['partys']:
            if not 'qual' in party:
                edi_db.message_post(cr, uid, document.id, body='Error found: could not find field: qual (partner).')
                return False
            if not 'gln' in party:
                edi_db.message_post(cr, uid, document.id, body='Error found: could not find field: gln (partner).')
                return False
            pids = partner_db.search(cr, uid,[('ref', '=', party['gln'])])
            if not pids:
                edi_db.message_post(cr, uid, document.id, body='Error found: could not resolve partner {!s}.'.format(party['gln']))
                return False
            if party['qual'] == 'BY':
                found_by = True
            elif party['qual'] == 'DP':
                found_dp = True
            elif party['qual'] == 'IV':
                found_iv = True
        if not found_by or not found_dp or not found_iv:
            edi_db.message_post(cr, uid, document.id, body='Error found: couldnt find all required partners BY,DP and IV.')
            return False





        # Validate all the line items
        # ---------------------------
        if not 'lines' in data:
            edi_db.message_post(cr, uid, document.id, body='Error found: could not find field: lines.')
            return False
        try:
            data['lines'] = data['lines'][0]['line']
        except Exception:
            edi_db.message_post(cr, uid, document.id, body='Error found: erroneous structure for table: lines.')
            return False
        if len(data['lines']) == 0:
            edi_db.message_post(cr, uid, document.id, body='Error found: content of table lines is empty. ')
            return False

        product = self.pool.get('product.product')
        for line in data['lines']:
            if not 'ordqua' in line:
                edi_db.message_post(cr, uid, document.id, body='Error found: could not find field: ordqua (line).')
                return False
            if line['ordqua'] < 1:
                edi_db.message_post(cr, uid, document.id, body='Error found: ordqua (line) should be larger than 0.')
                return False
            if not 'gtin' in line:
                edi_db.message_post(cr, uid, document.id, body='Error found: could not find field: gtin (line).')
                return False
            pids = product.search(cr, uid,[('ean13', '=', line['gtin'])])
            if not pids:
                edi_db.message_post(cr, uid, document.id, body='Error found: could not resolve product {!s}.'.format(line['gtin']))
                return False


        # Validate timing information
        # ---------------------------
        if not 'deldtm' in data:
            edi_db.message_post(cr, uid, document.id, body='Error found: could not find field: deldtm.')
            return False
        if not 'docdtm' in data:
            edi_db.message_post(cr, uid, document.id, body='Error found: could not find field: docdtm.')
            return False


        # If we get all the way to here, the document is valid
        # ----------------------------------------------------
        return True







    ''' sale.order:edi_import()
        --------------------------------------------
        This method will perform the actual import of the
        provided EDI Document.
        ------------------------------------------------- '''
    def edi_import(self, cr, uid, ids, context):

        # Attempt to validate the file right before processing
        # ----------------------------------------------------
        edi_db = self.pool.get('clubit.tools.edi.document.incoming')
        if not self.edi_import_validator(cr, uid, ids, context):
            edi_db.message_post(cr, uid, ids, body='Error found: during processing, the document was found invalid.')
            return False


        # Process the EDI Document
        # ------------------------
        document = edi_db.browse(cr, uid, ids, context)
        data = json.loads(document.content)
        data = data['message']
        data['partys'] = data['partys'][0]['party']
        data['lines'] = data['lines'][0]['line']
        name = self.create_sale_order(cr, uid, data, context)
        if not name:
            edi_db.message_post(cr, uid, ids, body='Error found: something went wrong while creating the sale order.')
            return False
        else:
            edi_db.message_post(cr, uid, ids, body='Sale order {!s} created'.format(name))
            return True








    ''' sale.order:create_sale_order()
        --------------------------------------------
        This method will create a sales order based
        on the provided EDI input.
        -------------------------------------------- '''
    def create_sale_order(self, cr, uid, data, context):

        # Prepare the call to create a sale order
        # ---------------------------------------
        param = {}
        param['origin']               = data['docnum']
        param['message_follower_ids'] = False
        param['categ_ids']            = False
        param['picking_policy']       = 'one'
        param['order_policy']         = 'picking'
        param['carrier_id']           = False
        param['invoice_quantity']     = 'order'
        param['client_order_ref']     = data['docnum']
        param['date_order']           = data['deldtm'][:4] + '-' + data['deldtm'][4:-2] + '-' + data['deldtm'][6:]
        param['message_ids']          = False
        param['note']                 = False
        param['project_id']           = False
        param['incoterm']             = False
        param['section_id']           = False
        param['shop_id']              = self._get_default_shop(cr, uid, context)


        # Enter all partner data
        # ----------------------
        partner_db = self.pool.get('res.partner')
        fiscal_pos = False

        for party in data['partys']:
            if party['qual'] == 'BY':
                pids = partner_db.search(cr, uid,[('ref', '=', party['gln'])])
                brico = partner_db.browse(cr, uid, pids, context)[0]
                param['partner_id']          = brico.id
                param['user_id']             = brico.user_id.id
                param['fiscal_position']     = brico.property_account_position.id
                param['payment_term']        = brico.property_payment_term.id
                param['pricelist_id']        = brico.property_product_pricelist.id
                fiscal_pos = self.pool.get('account.fiscal.position').browse(cr, uid, brico.property_account_position.id) or False

            if party['qual'] == 'IV':
                pids = partner_db.search(cr, uid,[('ref', '=', party['gln'])])
                iv = partner_db.browse(cr, uid, pids, context)[0]
                param['partner_invoice_id']  = iv.id

            if party['qual'] == 'DP':
                pids = partner_db.search(cr, uid,[('ref', '=', party['gln'])])
                dp = partner_db.browse(cr, uid, pids, context)[0]
                param['partner_shipping_id']  = dp.id

        if 'partner_shipping_id' not in param:
            param['partner_shipping_id'] = param['partner_id']
        if 'user_id' not in param:
            param['user_id'] = uid
        elif not param['user_id']:
            param['user_id'] = uid



        # Create the line items
        # ---------------------
        product_db = self.pool.get('product.product')
        pricelist_db = self.pool.get('product.pricelist')
        param['order_line'] = []
        for line in data['lines']:

            pids = product_db.search(cr, uid,[('ean13', '=', line['gtin'])])
            prod = product_db.browse(cr, uid, pids, context)[0]

            detail = {}
            detail['property_ids']          = False
            detail['product_uos_qty']       = line['ordqua']
            detail['product_id']            = prod.id
            detail['product_uom']           = prod.uom_id.id

            # If the price is given from the file, use that
            # Otherwise, use the price from the pricelist
            if 'price' in line:
                detail['price_unit'] = line['price']
            else:
                detail['price_unit'] = pricelist_db.price_get(cr,uid,[param['pricelist_id']], prod.id, 1, brico.id)[param['pricelist_id']]

            detail['product_uom_qty']       = line['ordqua']
            detail['customer_product_code'] = False
            detail['name']                  = prod.name
            detail['delay']                 = False
            detail['discount']              = False
            detail['address_allotment_id']  = False
            detail['th_weight']             = prod.weight * int(line['ordqua'])
            detail['product_uos']           = False
            detail['type']                  = 'make_to_stock'
            detail['product_packaging']     = False


#           Tax swapping calculations     u'tax_id': [[6,False, [1,3] ]],
#           -------------------------
            detail['tax_id'] = False
            if prod.taxes_id:
                detail['tax_id']            = [[6,False,[]]]
                if fiscal_pos:
                    new_taxes =  self.pool.get('account.fiscal.position').map_tax(cr, uid, fiscal_pos, prod.taxes_id)
                    if new_taxes:
                        detail['tax_id'][0][2] = new_taxes
                    else:
                        for tax in prod.taxes_id:
                            detail['tax_id'][0][2].append(tax.id)
                else:
                    for tax in prod.taxes_id:
                        detail['tax_id'][0][2].append(tax.id)





            order_line = []
            order_line.extend([0])
            order_line.extend([False])
            order_line.append(detail)
            param['order_line'].append(order_line)



        # Actually create the sale order
        # ------------------------------
        sid = self.create(cr, uid, param, context=None)
        so = self.browse(cr, uid, [sid], context)[0]
        return so.name





# {
#     u'origin': False,
#     u'message_follower_ids': False,
#     u'categ_ids': [
#         [
#             6,
#             False,
#             [
#
#             ]
#         ]
#     ],
#     u'order_line': [
#         [
#             0,
#             False,
#             {
#                 u'property_ids': [
#                     [
#                         6,
#                         False,
#                         [
#
#                         ]
#                     ]
#                 ],
#                 u'product_uos_qty': 1,
#                 u'product_id': 9,
#                 u'product_uom': 1,
#                 u'price_unit': 17,
#                 u'product_uom_qty': 1,
#                 u'customer_product_code': u'BRIC0001',
#                 u'name': u'Product1',
#                 u'delay': 7,
#                 u'discount': 0,
#                 u'address_allotment_id': False,
#                 u'th_weight': 4,
#                 u'product_uos': False,
#                 u'tax_id': [
#                     [
#                         6,
#                         False,
#                         [
#                             1
#                         ]
#                     ]
#                 ],
#                 u'type': u'make_to_stock',
#                 u'product_packaging': False
#             }
#         ]
#     ],
#     u'picking_policy': u'direct',
#     u'order_policy': u'manual',
#     u'carrier_id': 2,
#     u'invoice_quantity': u'order',
#     u'client_order_ref': u'erergergerg',
#     u'date_order': u'2013-08-01',
#     u'partner_id': 7,
#     u'message_ids': False,
#     u'fiscal_position': False,
#     u'user_id': 1,
#     u'payment_term': False,
#     u'note': False,
#     u'pricelist_id': 1,
#     u'project_id': False,
#     u'incoterm': False,
#     u'section_id': False,
#     u'partner_invoice_id': 7,
#     u'partner_shipping_id': 7,
#     u'shop_id': 1
# }



