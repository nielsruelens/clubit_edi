from openerp.osv import osv, fields
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
    EDI Structures for the outgoing interface.
-------------------------------------------------------------------------------
"""

LINE = {
    'ARTIKEL': '',                  #account.invoice.line:product_id -> product.product:ean13
    'ARTIKELREF': '',               #account.invoice.line:product_id -> product.product:name
    'ARTIKELOMSCHRIJVING': '',      #account.invoice.line:product_id -> product.product:sale_description
    'AANTAL': '',                   #account.invoice.line:quantity
    'AANTALGELEVERD': '',           #account.invoice.line:quantity
    'LIJNTOTAAL': 0,                #account.invoice.line:price_subtotal
    'UNITPRIJS': 0,                 #account.invoice.line:price_unit
    'BTWPERCENTAGE': 0,             #account.invoice.line.vat (met naam VAT*) account.tax:amount * 100
    'LIJNTOTAALBELAST': 0,          #account.invoice.line:price_subtotal
    'BEBAT': 0,                     #account.invoice.line:vat (alle VAT's met naam "Bebat") som van account.tax:amount
    'BEBATLIJN': 0,                 #account.invoice.line:quantity * BEBAT (zie vorige lijn)
    'RECUPEL': 0,                   #account.invoice.line:vat (alle VAT's met naam "Recupel") som van account.tax:amount
    'RECUPELLIJN': 0,               #account.invoice.line:quantity * RECUPEL (zie vorige lijn)
}

INVOICE = {
    'FACTUURNUMMER': '',            #account.invoice:number
    'DATUM': '',                    #account.invoice:create_date
    'FACTUURDATUM': '',             #account.invoice:date_invoice
    'LEVERDATUM': '',               #account.invoice:origin -> stock.picking.out:date_done
    'KLANTREFERENTIE': '',          #account.invoice:name
    'REFERENTIEDATUM': '',          #account.invoice:origin -> sale.order:date_order
    'LEVERINGSBON': '',             #account.invoice:origin -> stock.picking.out:name
    'LEVERPLANDATUM': '',           #account.invoice:origin -> stock.picking.out:min_date
    'AANKOPER': '',                 #account.invoice:origin -> sale.order:partner_id -> res.partner:ref
    'LEVERANCIER': '',              #res.company:partner_id -> res.partner:ref  (er is normaal maar 1 company)
    'BTWLEVERANCIER': '',           #res.company:partner_id -> res.partner:vat  (er is normaal maar 1 company)
    'LEVERPLAATS': '',              #account.invoice:origin -> stock.picking.out:partner_id -> res.partner:ref
    'FACTUURPLAATS': '',            #account.invoice:partner_id -> res.partner:ref
    'BTWFACTUUR': '',               #account.invoice:partner_id -> res.partner:vat
    'VALUTA': 'EUR',
    'LIJNEN': [],
    'FACTUURPERCENTAGE': 0,
    'FACTUURTOTAAL': 0,             #account.invoice:amount_total
    'FACTUURMVH': 0,                #account.invoice:amount_untaxed
    'FACTUURSUBTOTAAL': 0,          #account.invoice:amount_untaxed
    'TOTAALBTW': 0,                 #account.invoice:amount_untaxed * 1,21 - amount_untaxed
    'BEBATTOTAAL': 0,               #som van alle line items: BEBATLIJN
    'RECUPELTOTAAL': 0,             #som van alle line items: RECUPELLIJN
}



##############################################################################
#
#    account.invoice
#
#    This class extends the standard account.invoice class to add
#    exporting EDI functionality.
#
##############################################################################
class account_invoice(osv.Model, EDIMixin):
    _name = "account.invoice"
    _inherit = "account.invoice"



    ''' account.invoice:_function_edi_sent_get()
        --------------------------------------
        This method calculates the value of field edi_sent by
        looking at the database and checking for EDI docs
        on this invoice.
        ------------------------------------------------------ '''
    def _function_edi_sent_get(self, cr, uid, ids, field, arg, context=None):
        edi_db = self.pool.get('clubit.tools.edi.document.outgoing')
        flow_db = self.pool.get('clubit.tools.edi.flow')
        flow_id = flow_db.search(cr, uid, [('model', '=', 'account.invoice'),('method', '=', 'send_edi_out')])[0]
        res = dict.fromkeys(ids, False)
        for invoice in self.browse(cr, uid, ids, context=context):
            docids = edi_db.search(cr, uid, [('flow_id', '=', flow_id),('reference', '=', invoice.number)])
            if not docids: continue
            edi_docs = edi_db.browse(cr, uid, docids, context=context)
            edi_docs.sort(key = lambda x: x.create_date, reverse=True)
            res[invoice.id] = edi_docs[0].create_date
        return res


    _columns = {
        'edi_sent': fields.function(_function_edi_sent_get, type='datetime', string='EDI sent'),
    }






    ''' account.invoice:edi_partner_resolver()
        --------------------------------------
        This method attempts to find the correct partner
        to whom we should send an DESADV document for a
        number of deliveries.
        ------------------------------------------------ '''
    def edi_partner_resolver(self, cr, uid, ids, context):

        result_list = []
        for invoice in self.browse(cr, uid, ids, context):
            result_list.append({'id' : invoice.id, 'partner_id': invoice.partner_id.id})
        return result_list





    ''' account.invoice:send_edi_out()
        ------------------------------
        This method will perform the export of an invoice.
        Only invoices that are in state 'open' are allowed.
        --------------------------------------------------- '''
    def send_edi_out(self, cr, uid, items, context=None):


        edi_db = self.pool.get('clubit.tools.edi.document.outgoing')

        # Get the selected items
        # ----------------------
        invoices = [x['id'] for x in items]
        invoices = self.browse(cr, uid, invoices, context=context)


        # Loop over all invoices to see if they're all open
        # -------------------------------------------------
        for invoice in invoices:
            if invoice.state != 'open':
                raise osv.except_osv(_('Warning!'), _("Not all documents had state 'open'. Please exclude these documents."))



        # Actual processing of all the invoices
        # ---------------------------------------
        for invoice in invoices:
            content = self.edi_export(cr, uid, invoice, None, context)
            partner_id = [x['partner_id'] for x in items if x['id'] == invoice.id][0]
            result = edi_db.create_from_content(cr, uid, invoice.number, content, partner_id, 'account.invoice', 'send_edi_out')
            if result != True:
                raise osv.except_osv(_('Error!'), _("Something went wrong while trying to create one of the EDI documents. Please contact your system administrator. Error given: {!s}").format(result))



    def edi_export(self, cr, uid, invoice, edi_struct=None, context=None):
        """This method creates an EDI dictionary of an invoice.
           The output dict is so radically different from a standard
           EDI document that we have to write a complete custom method.

           Args:
               invoice: the actual object to be processed.

           Returns:
               edi_doc: EDI invoice.
        """

        # Instantiate variables
        # ---------------------
        edi_doc = copy.deepcopy(dict(INVOICE))

        ref = invoice.origin.partition(':')
        pick_db    = self.pool.get('stock.picking.out')
        order_db   = self.pool.get('sale.order')
        partner_db = self.pool.get('res.partner')
        tax_db     = self.pool.get('account.tax')
        product_db = self.pool.get('product.product')
        company_db = self.pool.get('res.company')

        do_id = pick_db.search(cr, uid,[('name', '=', ref[0])])
        if not do_id:
            raise osv.except_osv(_('Warning!'), _("Could not find delivery for invoice: {!s}").format(invoice.number))

        so_id = order_db.search(cr, uid,[('name', '=', ref[2])])
        if not so_id:
            raise osv.except_osv(_('Warning!'), _("Could not find order for invoice: {!s}").format(invoice.number))

        co_id  = company_db.search(cr, uid, [])[0]

        delivery = pick_db.browse(cr, uid, do_id, context)[0]
        order    = order_db.browse(cr, uid, so_id, context)[0]
        company  = company_db.browse(cr, uid, co_id, context)
        now = datetime.datetime.now()



        # Basic header fields
        # -------------------
        edi_doc['FACTUURNUMMER']    = invoice.number
        edi_doc['DATUM']            = now.strftime("%Y%m%d")
        edi_doc['FACTUURDATUM']     = invoice.date_invoice.replace('-','')
        edi_doc['KLANTREFERENTIE']  = invoice.name
        edi_doc['FACTUURTOTAAL']    = invoice.amount_total
        edi_doc['FACTUURSUBTOTAAL'] = invoice.amount_untaxed


        ## edi_doc['TOTAALBTW'] = float('%.2f' % ((invoice.amount_untaxed + edi_doc['BEBATTOTAAL'] + edi_doc['RECUPELTOTAAL'])

        partner = partner_db.browse(cr, uid, invoice.partner_id.id, context)
        if partner:
            edi_doc['FACTUURPLAATS']  = partner.ref
            edi_doc['BTWFACTUUR']  = partner.vat
        if company:
            partner = partner_db.browse(cr, uid, company.partner_id.id, context)
            if partner:
                edi_doc['LEVERANCIER']  = partner.ref
                edi_doc['BTWLEVERANCIER']  = partner.vat



        # Delivery order fields
        # ---------------------
        d = datetime.datetime.strptime(delivery.date_done, "%Y-%m-%d %H:%M:%S")
        edi_doc['LEVERDATUM']      = d.strftime("%Y%m%d")
        edi_doc['LEVERINGSBON']    = delivery.name

        d = datetime.datetime.strptime(delivery.min_date, "%Y-%m-%d %H:%M:%S")
        edi_doc['LEVERPLANDATUM']  = d.strftime("%Y%m%d")
        partner = partner_db.browse(cr, uid, delivery.partner_id.id, context)
        if partner:
            edi_doc['LEVERPLAATS']  = partner.ref


        # Sale order fields
        # -----------------
        d = datetime.datetime.strptime(order.date_order, "%Y-%m-%d")
        edi_doc['REFERENTIEDATUM']  = d.strftime("%Y%m%d")
        partner = partner_db.browse(cr, uid, order.partner_id.id, context)
        if partner:
            edi_doc['AANKOPER']     = partner.ref


        # Line items
        # ----------
        for line in invoice.invoice_line:
            product = product_db.browse(cr, uid, line.product_id.id, context)
            edi_line = copy.deepcopy(dict(LINE))
            edi_line['ARTIKEL']             = product.ean13
            edi_line['ARTIKELREF']          = product.name
            edi_line['ARTIKELOMSCHRIJVING'] = product.name
            edi_line['AANTAL']              = line.quantity
            edi_line['AANTALGELEVERD']      = line.quantity
            edi_line['LIJNTOTAAL']          = line.price_subtotal

            edi_line['UNITPRIJS']           = line.price_unit
            edi_line['LIJNTOTAALBELAST']    = line.price_subtotal

            for line_tax in line.invoice_line_tax_id:
                vat = tax_db.browse(cr, uid, line_tax.id, context)
                if "Bebat" in vat.name:
                    edi_line['BEBAT'] += vat.amount
                elif "Recupel" in vat.name:
                    edi_line['RECUPEL'] += vat.amount
                elif "VAT" in vat.name:
                    edi_line['BTWPERCENTAGE'] = int(vat.amount*100)
                    edi_doc['FACTUURPERCENTAGE'] = edi_line['BTWPERCENTAGE']

            if edi_line['BEBAT'] != True:
                edi_line['BEBATLIJN'] = edi_line['BEBAT'] * line.quantity
            else:
                edi_line['BEBATLIJN'] = 0
            if edi_line['RECUPEL'] != True:
                edi_line['RECUPELLIJN'] = edi_line['RECUPEL'] * line.quantity
            else:
                edi_line['RECUPELLIJN'] = 0

            edi_doc['LIJNEN'].append(edi_line)

        # Final BEBAT & RECUPEL calculations
        # ----------------------------------
        for line in edi_doc['LIJNEN']:
            edi_doc['BEBATTOTAAL']   += line['BEBATLIJN']
            edi_doc['RECUPELTOTAAL'] += line['RECUPELLIJN']

        # Final tax calculation
        # ---------------------
        edi_doc['TOTAALBTW'] = float('%.2f' % ((invoice.amount_untaxed + edi_doc['BEBATTOTAAL'] + edi_doc['RECUPELTOTAAL']) * edi_doc['FACTUURPERCENTAGE']/100))
        edi_doc['FACTUURMVH']       = invoice.amount_untaxed + edi_doc['BEBATTOTAAL'] + edi_doc['RECUPELTOTAAL']



        # Return the result
        # -----------------
        return edi_doc
