from openerp.osv import osv,fields
from openerp.addons.edi import EDIMixin
import datetime
import json
import copy

import shutil
from os import listdir
from os.path import isfile, join
from openerp.tools.translate import _


"""
-------------------------------------------------------------------------------
    EDI Structures for the outgoing interface to VRD
-------------------------------------------------------------------------------
"""

DELIVERY_ORDER_PRODUCT_EDI_STRUCT = {
    'name': True,
    'ean13': True,
}

DELIVERY_ORDER_LINE_EDI_STRUCT = {
    'product_qty': True,
    'product_uom': True,
    'name': True,
    'weight': True,
    'weight_net': True,
    'origin': True,
    'picking_id': True,
    'type': True,
    'location_id': True,
    'sale_line_id': True,
    'location_dest_id': True,
    'customer_product_code': True,
}

DELIVERY_ORDER_PARTNER_EDI_STRUCT = {
    'name': True,
    'ref': True,
    'lang': True,
    'website': True,
    'email': True,
    'street': True,
    'street2': True,
    'zip': True,
    'city': True,
    'country_id': True,
    'state_id': True,
    'phone': True,
    'fax': True,
    'mobile': True,
    'vat': True,
}

DELIVERY_ORDER_EDI_STRUCT = {
    'name': True,
    'state' : True,
    'date': True,
    'min_date': True,
    'origin': True,
    'move_type': True,
    'number_of_packages': True,
    'carrier_tracking_ref': True,
    'order_reference': True,
    'note': True,
    'move_lines': DELIVERY_ORDER_LINE_EDI_STRUCT,
}




class stock_picking(osv.Model):
    _name = "stock.picking"
    _inherit = "stock.picking"


    ''' stock.picking:_function_edi_sent_get()
        --------------------------------------
        This method calculates the value of field edi_sent by
        looking at the database and checking for EDI docs
        on this delivery.
        ------------------------------------------------------ '''
    def _function_edi_sent_get(self, cr, uid, ids, field, arg, context=None):
        edi_db = self.pool.get('clubit.tools.edi.document.outgoing')
        flow_db = self.pool.get('clubit.tools.edi.flow')
        flow_id = flow_db.search(cr, uid, [('model', '=', 'stock.picking.out'),('method', '=', 'send_edi_out')])[0]
        res = dict.fromkeys(ids, False)
        for pick in self.browse(cr, uid, ids, context=context):
            docids = edi_db.search(cr, uid, [('flow_id', '=', flow_id),('reference', '=', pick.name)])
            if not docids: continue
            edi_docs = edi_db.browse(cr, uid, docids, context=context)
            edi_docs.sort(key = lambda x: x.create_date, reverse=True)
            res[pick.id] = edi_docs[0].create_date
        return res


    _columns = {
        'edi_sent': fields.function(_function_edi_sent_get, type='datetime', string='EDI sent'),
    }






"""
-------------------------------------------------------------------------------
    Redefinition of stock.picking.out for both in and outgoing EDI.
-------------------------------------------------------------------------------
"""
class stock_picking_out(osv.Model, EDIMixin):
    _name = "stock.picking.out"
    _inherit = "stock.picking.out"



    ''' stock.picking:_function_edi_sent_get()
        --------------------------------------
        ATTENTION: The reason this method is declared twice,
        here and in the superclass is because inheritance is
        BROKEN FOR STOCK.PICKING & STOCK.PICKING.IN/OUT
        ----------------------------------------------------- '''
    def _function_edi_sent_get(self, cr, uid, ids, field, arg, context=None):
        return False


    _columns = {
        'edi_sent': fields.function(_function_edi_sent_get, type='datetime', string='EDI sent'),
    }




    ''' stock.picking.out:edi_import_validator()
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

        if len(data) > 1:
            edi_db.message_post(cr, uid, document.id, body='Error found: more than 1 line found at root level.')
            return False

        data = data[0]


        # Validate the state field
        # ------------------------
        if not 'state' in data:
            edi_db.message_post(cr, uid, document.id, body='Error found: could not find field: state.')
            return False
        if data['state'] != 'done' and data['state'] != 'altered' and data['state'] != 'cancelled':
            edi_db.message_post(cr, uid, document.id, body='Error found: state field can only be one of these 3: done, altered or cancelled.')
            return False

        # Validate the __id field
        # -----------------------
        if not '__id' in data:
            edi_db.message_post(cr, uid, document.id, body='Error found: could not find field: __id.')
            return False
        if not data['__id']:
            edi_db.message_post(cr, uid, document.id, body='Error found: __id field cannot be empty.')
            return False
        pick = False
        try:
            pick = self._edi_get_object_by_external_id(cr, uid, data['__id'], 'stock.picking.out', context=context)
        except Exception:
            edi_db.message_post(cr, uid, document.id, body='Error found: __id field could not be resolved to a delivery order.')
            return False
        if not pick or pick == None:
            edi_db.message_post(cr, uid, document.id, body='Error found: __id field could not be resolved to a delivery order.')
            return False

        # Validate that this document is still open for changes
        # -----------------------------------------------------
        if pick.state == 'done' or pick.state == 'cancel':
            edi_db.message_post(cr, uid, document.id, body='Error found: delivery order {!s} is already fully processed and in state "done" or "cancelled"'.format(pick.name))
            return False



        # Additional validations only required in case of altered
        # -------------------------------------------------------
        if data['state'] != 'altered':
            return True


        if 'move_lines' not in data:
            edi_db.message_post(cr, uid, document.id, body='Error found: could not find field: move_lines.')
            return False
        if len(data['move_lines']) == 0:
            edi_db.message_post(cr, uid, document.id, body='Error found: move_lines did not contain any data.')
            return False


        # Validate the line items
        # -----------------------
        for line in data['move_lines']:
            if not 'state' in line:
                edi_db.message_post(cr, uid, document.id, body='Error found: could not find field: state (line item).')
                return False
            if line['state'] != 'done' and line['state'] != 'altered' and line['state'] != 'cancelled':
                edi_db.message_post(cr, uid, document.id, body='Error found: state field (line item) can only be one of these 3: done, altered or cancelled.')
                return False

            if not '__id' in line:
                edi_db.message_post(cr, uid, document.id, body='Error found: could not find field: __id (line item).')
                return False
            if not line['__id']:
                edi_db.message_post(cr, uid, document.id, body='Error found: __id (line item) field cannot be empty.')
                return False
            item = False
            try:
                item = self._edi_get_object_by_external_id(cr, uid, line['__id'], 'stock.move', context=context)
            except Exception:
                edi_db.message_post(cr, uid, document.id, body='Error found: __id (line item) field could not be resolved to a Line Item.')
                return False
            if not item:
                edi_db.message_post(cr, uid, document.id, body='Error found: __id (line item) field could not be resolved to a Line Item.')
                return False

            if line['state'] == 'altered':
                if not 'product_qty' in line:
                    edi_db.message_post(cr, uid, document.id, body='Error found: could not find field: product_qty (line item).')
                    return False
                if not isinstance(line['product_qty'], float):
                    edi_db.message_post(cr, uid, document.id, body='Error found: field product_qty (line item) was not a float.')
                    return False


        # If we get all the way to here, the document is valid
        # ----------------------------------------------------
        return True




    ''' stock.picking.out:edi_partner_resolver()
        ----------------------------------------
        This method attempts to find the correct partner
        to whom we should send an EDI document for a
        number of deliveries.
        ------------------------------------------------ '''
    def edi_partner_resolver(self, cr, uid, ids, context):

        result_list = []
        for pick in self.browse(cr, uid, ids, context):
            result_list.append({'id' : pick.id, 'partner_id': pick.partner_id.id})
        return result_list



    ''' stock.picking.out:edi_import()
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


        # Read the EDI Document
        # ---------------------
        document = edi_db.browse(cr, uid, ids, context)
        data = json.loads(document.content)[0]


        # Forward processing to the correct sub-handler
        # ---------------------------------------------
        if data['state'] == 'done':
            result, message = self.process_incoming_edi_simple(cr, uid, data, context)
        elif data['state'] == 'cancelled':
            result, message = self.process_incoming_edi_cancel(cr, uid, data, context)
        elif data['state'] == 'altered':
            result, message = self.process_incoming_edi_altered(cr, uid, data, context)

        if message:
            edi_db.message_post(cr, uid, ids, body=message)
        return result





    ''' stock.picking.out:process_incoming_edi_simple()
        --------------------------------------------
        This method will perform the import of a delivery
        order that was delivered without any changes.
        ------------------------------------------------- '''
    def process_incoming_edi_simple(self, cr, uid, data, context):

        # Try to find the document
        # ------------------------
        pick = self._edi_get_object_by_external_id(cr, uid, data['__id'], 'stock.picking.out', context=context)

        # Prepare the call to do_partial()
        # --------------------------------
        param = {}
        for line in pick.move_lines:
            move = {}
            move['prodlot_id'] = False
            move['product_id'] = line.product_id.id
            move['product_uom'] = line.product_uom.id
            move['product_qty'] = line.product_qty
            param["move" + str(line.id)] = move


        # Make the call to do_partial() to set the document to 'done'
        # -----------------------------------------------------------
        try:
            self.do_partial(cr, uid, [pick.id], param, context)
        except Exception:
            return False, 'Error found: the call to do_partial() failed.'

        # Check that our operation actually happened
        # ------------------------------------------
        pick = self._edi_get_object_by_external_id(cr, uid, data['__id'], 'stock.picking.out', context=context)
        if pick.state != 'done':
            return False, 'Error found: the document did not have state "done" after processing.'
        return True, ''




    ''' stock.picking.out:process_incoming_edi_cancel()
        --------------------------------------------
        This method will perform the import of a delivery
        order that was cancelled.
        ------------------------------------------------- '''
    def process_incoming_edi_cancel(self, cr, uid, data, context):

        pick = self._edi_get_object_by_external_id(cr, uid, data['__id'], 'stock.picking.out', context=context)
        self.action_cancel(cr, uid, [pick.id], context)

        # Check that our operation actually happened
        # ------------------------------------------
        pick = self._edi_get_object_by_external_id(cr, uid, data['__id'], 'stock.picking.out', context=context)
        if pick.state != 'cancel':
            return False, 'Error found: the document did not have state "cancel" after processing.'
        return True, ''



    ''' stock.picking.out:process_incoming_edi_altered()
        --------------------------------------------
        This method will perform the import of a delivery
        order that was altered.
        ------------------------------------------------- '''
    def process_incoming_edi_altered(self, cr, uid, data, context):

        # Try to find the document
        # ------------------------
        pick = self._edi_get_object_by_external_id(cr, uid, data['__id'], 'stock.picking.out', context=context)

        # Prepare the call to do_partial()
        # --------------------------------
        param = {}
        for edi_move_line in data['move_lines']:

            if edi_move_line['state'] == 'cancelled':
                continue

            line = self._edi_get_object_by_external_id(cr, uid, edi_move_line['__id'], 'stock.move', context=context)
            move = {}
            move['prodlot_id'] = False
            move['product_id'] = line.product_id.id
            move['product_uom'] = line.product_uom.id

            if edi_move_line['state'] == 'altered':
                move['product_qty'] = edi_move_line['product_qty']
            else:
                move['product_qty'] = line.product_qty
            param["move" + str(line.id)] = move


        # Make the call to do_partial() to set the document to 'done'
        # -----------------------------------------------------------
        try:
            self.do_partial(cr, uid, [pick.id], param, context)
        except Exception:
            return False, 'Error found: the call to do_partial() failed.'

        # Check that our operation actually happened
        # ------------------------------------------
        #pick = self._edi_get_object_by_external_id(cr, uid, data['__id'], 'stock.picking.out', context=context)
        #if pick.state != 'assigned':
        #    return False, 'Error found: the document did not have state "assigned" after processing.'
        return True, ''





    ''' stock.picking.out:send_edi_out()
        --------------------------------
        This method will perform the export of a delivery
        order, the simple version. Only deliveries that
        are in state 'assigned' or 'confirmed' may be
        passed to this method, otherwise an error will
        occur.
        ------------------------------------------------- '''
    def send_edi_out(self, cr, uid, items, context=None):


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
            if pick.state not in ['assigned', 'confirmed']:
                nope += pick.name + ', '
        if nope:
            raise osv.except_osv(_('Warning!'), _("Not all documents had states 'assigned' or 'confirmed'. Please exclude the following documents: {!s}").format(nope))


        # Actual processing of all the deliveries
        # ---------------------------------------
        for pick in pickings:
            content = self.edi_export(cr, uid, pick, None, context)
            partner_id = [x['partner_id'] for x in items if x['id'] == pick.id][0]
            result = edi_db.create_from_content(cr, uid, pick.name, content, partner_id, 'stock.picking.out', 'send_edi_out')
            if result != True:
                raise osv.except_osv(_('Error!'), _("Something went wrong while trying to create one of the EDI documents. Please contact your system administrator. Error given: {!s}").format(result))









    ''' stock.picking.out:edi_export()
        ------------------------------
        This method parses a given object to a JSON
        EDI structure.
        ------------------------------------------- '''
    def edi_export(self, cr, uid, pick, edi_struct=None, context=None):

        # Instantiate variables
        # ---------------------
        edi_doc_list = []
        edi_struct = dict(edi_struct or DELIVERY_ORDER_EDI_STRUCT)
        partner_struct = dict(DELIVERY_ORDER_PARTNER_EDI_STRUCT)
        customer = self.pool.get('res.partner')

        # Generate the super.edi_export() data
        # ------------------------------------
        edi_doc = super(stock_picking_out, self).edi_export(cr, uid, [pick], edi_struct, context)[0]

        # Add additional information: m2o fields don't work out of the box
        # ----------------------------------------------------------------
        edi_doc.update({
            'partner_id': customer.edi_export(cr, uid, [pick.partner_id], edi_struct=partner_struct, context=context)[0],
        })

        # Strip undesired content
        # -----------------------
        edi_doc = self.strip_document(edi_doc)

        # Return the result
        # -----------------
        edi_doc_list.append(edi_doc)
        return edi_doc_list






    def strip_document(self, edi_doc):
        """This method manipulates an edi document.

           The incoming EDI document is stripped of a number of OpenERP generated
           fields so it becomes more legible. On top of that, the fields are also
           ordered in a specific way to further increase readability.

           Args:
               edi_doc_list: the document that we're stripping.

           Returns:
               edi_doc_list: after stripping took place.
        """

        # Remove irrelevant HEADER fields
        # -------------------------------
        edi_doc = self.openerp_stripper(edi_doc)
        if 'partner_id' in edi_doc:
            edi_doc['partner_id'] = self.openerp_stripper(edi_doc['partner_id'])


        # Perform HEADER formatting
        # -------------------------
        if 'date' in edi_doc:
            edi_doc['date'] = edi_doc['date'][:10]  # remove time
        if 'min_date' in edi_doc:
            edi_doc['min_date'] = edi_doc['min_date'][:10]  # remove time
        if 'partner_id' in edi_doc:
            c = edi_doc['partner_id']
            if 'country_id' in c:
                edi_doc['partner_id']['country_id'] = edi_doc['partner_id']['country_id'][1]  # remove id
            if 'state_id' in c:
                edi_doc['partner_id']['state_id'] = edi_doc['partner_id']['state_id'][1]  # remove id


        # Remove irrelevant LINE ITEM fields
        # ----------------------------------
        for line in edi_doc['move_lines']:
            line = self.openerp_stripper(line)
            if 'product_id' in line:
                line['product_id'] = self.openerp_stripper(line['product_id'])
            if 'location_dest_id' in line:
                line['location_dest_id'] = self.openerp_stripper(line['location_dest_id'])

            # Simplify lists that should just be fields
            # -----------------------------------------
            if 'location_dest_id' in line:
                l = line['location_dest_id']
                if 'country_id' in l:
                    line['location_dest_id']['country_id'] = line['location_dest_id']['country_id'][1]  # remove id
                if 'state_id' in l:
                    line['location_dest_id']['state_id'] = line['location_dest_id']['state_id'][1]  # remove id

            if 'location_id' in line:
                line['location_id'] = line['location_id'][1]  # remove id
            if 'product_uom' in line:
                line['product_uom'] = line['product_uom'][1]  # remove id

        return edi_doc






    def openerp_stripper(self, record):
        """This method strips a number of fields from a dictionary.
           OpenERP adds a number of fields the customer doesn't want to the outgoing EDI file.
           This method strips these fields for a record.

           Args:
               record: the dictionary that we're stripping.

           Returns:
               record: after stripping took place.
        """

        if '__model' in record:             del record['__model']
        if '__last_update' in record:       del record['__last_update']
        if '__generator' in record:         del record['__generator']
        if '__generator_version' in record: del record['__generator_version']
        if '__version' in record:           del record['__version']
        if '__module' in record:            del record['__module']

        return record











class stock_move(osv.Model, EDIMixin):
    _inherit = "stock.move"

    # EDI export method for stock.move
    #--------------------------------
    def edi_export(self, cr, uid, records, edi_struct=None, context=None):

        # Instantiate variables
        edi_doc_list = []
        edi_struct = dict(edi_struct or DELIVERY_ORDER_LINE_EDI_STRUCT)
        product_struct = dict(DELIVERY_ORDER_PRODUCT_EDI_STRUCT)
        product = self.pool.get('product.product')
        partner_struct = dict(DELIVERY_ORDER_PARTNER_EDI_STRUCT)
        customer = self.pool.get('res.partner')

        for line in records:

            # Generate the super.edi_export() data
            edi_doc = super(stock_move, self).edi_export(cr, uid, [line], edi_struct, context)[0]

            # Add additional information m2o fields don't work out of the box
            edi_doc.update({
                'product_id': product.edi_export(cr, uid, [line.product_id], edi_struct=product_struct, context=context)[0],
                'location_dest_id': customer.edi_export(cr, uid, [line.partner_id], edi_struct=partner_struct, context=context)[0],
                # 'id': line._id,
            })

            edi_doc_list.append(edi_doc)


        # Return the result
        return edi_doc_list









class product_product(osv.Model, EDIMixin):
    _inherit = "product.product"










