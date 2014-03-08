from openerp.osv import osv, fields
from openerp.tools.translate import _
import re, netsvc, json
import datetime



##############################################################################
#
#    clubit.account.invoice.overview
#
#    This class gives users the ability to send an overview of all invoices
#    that were sent as EDI between a given datetime range to a given partner.
#
##############################################################################
class clubit_account_invoice_overview(osv.Model):
    _name = "clubit.account.invoice.overview"
    _inherit = ['mail.thread']
    _columns = {
        'from_date': fields.datetime('From', required=True),
        'to_date': fields.datetime('To', required=True),
        'partner_id': fields.many2one('res.partner', 'Send to', required=True),
        'content' : fields.text('Preview', readonly=True),
        'sent_at': fields.datetime('Sent At', readonly=True),
        'document_ids': fields.many2many('clubit.tools.edi.document.outgoing', 'clubit_edi_overview_document_rel','overview_id', 'document_id', 'EDI Documents', readonly=True),
    }



    ''' clubit.account.invoice.overview:calculate()
        -------------------------------------------
        This method calculates which documents are in scope
        for this overview depending on the from and to dates
        that are chosen.
        ---------------------------------------------------- '''
    def calculate(self, cr, uid, ids, context=None):

        assert len(ids) == 1

        overview = self.browse(cr, uid, ids, context=context)[0]
        assert overview.from_date
        assert overview.to_date


        # Find all documents in range
        # ---------------------------
        flow_id = self.pool.get('clubit.tools.edi.flow').search(cr, uid, [('model', '=', 'account.invoice'),('method', '=', 'send_edi_out')])[0]
        document_db = self.pool.get('clubit.tools.edi.document.outgoing')
        domain = [
            ('flow_id', '=', flow_id),
            ('partner_id', '=', overview.partner_id.id),
            ('create_date', '>=', overview.from_date),
            ('create_date', '<', overview.to_date)
        ]
        document_ids = document_db.search(cr, uid, domain, order='reference, create_date', context=context)

        if not document_ids:
            raise osv.except_osv(_('No EDI documents found!'), _('No EDI documents found within the given range.'))

        documents = document_db.browse(cr, uid, document_ids, context=context)


        # Filter documents so the invoice number is unique (keep most recent)
        # -------------------------------------------------------------------
        i = -1
        previous = False
        for document in documents[:]:
            i += 1
            if previous == False:
                previous = document
                continue
            elif previous.reference == document.reference:
                if previous.create_date >= document.create_date:
                    documents.pop(i)
                    document_ids.pop(i)
                elif previous.create_date < document.create_date:
                    documents.pop(i-1)
                    document_ids.pop(i-1)
                    previous = document
                    i -= 1
            else:
                previous = document

        # Build the content of the remaining documents
        # --------------------------------------------
        content = self.build_content(cr, uid, documents, overview, context)
        values = {'document_ids': [(6, 0, document_ids)],
                  'content': content}
        self.write(cr, uid, ids, values, context=context)









    ''' clubit.account.invoice.overview:build_content()
        -----------------------------------------------
        This method calculates the document contents.
        ----------------------------------------------- '''
    def build_content(self, cr, uid, documents, overview, context):


        result = '<html><table width="100%">'

        # Partnerdetails
        # --------------
        partner_db = self.pool.get('res.partner')
        company_db = self.pool.get('res.company')
        co_id  = company_db.search(cr, uid, [])[0]
        company  = company_db.browse(cr, uid, co_id, context)
        partner = partner_db.browse(cr, uid, company.partner_id.id, context)

        result += '<tr>'

        result += '<td colspan="2" valign="top">Afzender:</td><td colspan="2" valign="top">'
        if partner.name: result += partner.name + '<br/>'
        if partner.street: result += partner.street + '<br/>'
        if partner.street2: result += partner.street2 + '<br/>'
        if partner.zip: result += partner.zip + ' '
        if partner.city: result += partner.city
        if partner.vat: result += '<br/>' + partner.vat
        result += '</td>'



        result += '<td colspan="2" valign="top">Bestemmeling:</td><td colspan="2" valign="top">'
        if overview.partner_id.name: result += overview.partner_id.name + '<br/>'
        if overview.partner_id.street: result += overview.partner_id.street + '<br/>'
        if overview.partner_id.street2: result += overview.partner_id.street2 + '<br/>'
        if overview.partner_id.zip: result += overview.partner_id.zip + ' '
        if overview.partner_id.city: result += overview.partner_id.city
        if overview.partner_id.vat: result += '<br/>' + overview.partner_id.vat
        result += '</td></tr>'
        result += '<tr><td>&nbsp;</td></tr>'


        # Sending details
        # ---------------
        now = datetime.datetime.now()
        result += '<tr><td colspan="3">Verzendingsdatum: ' + now.strftime("%d/%m/%Y") + '</td>'
        result += '<td colspan="3">Interchange: ' + str(overview.id) + '</td></tr>'
        result += '<tr><td>&nbsp;</td></tr>'


        # Headers
        # -------
        result += '<tr>'
        result += '<td><strong>Nr factuur:</strong></td>'
        result += '<td><strong>Datum factuur:</strong></td>'
        result += '<td><strong>Nr bestelling:</strong></td>'
        result += '<td align="right"><strong>Bedrag excl. BTW:</strong></td>'
        result += '<td align="right"><strong>BTW:</strong></td>'
        result += '<td align="right"><strong>Bedrag incl. BTW:</strong></td>'
        result += '</tr>'


        # Content
        # -------
        tot_excl = 0
        btw = 0
        tot_incl = 0
        for document in documents:
            result += '<tr>'
            content = json.loads(document.content)
            result += '<td>' + content['FACTUURNUMMER'] + '</td>'
            result += '<td>' + content['FACTUURDATUM'] + '</td>'
            result += '<td>' + content['KLANTREFERENTIE'] + '</td>'
            result += '<td align="right">' + str(content['FACTUURMVH']) + '</td>'
            result += '<td align="right">' + str(content['TOTAALBTW']) + '</td>'
            result += '<td align="right">' + str(content['FACTUURTOTAAL']) + '</td>'
            result += '</tr>'

            tot_excl += content['FACTUURMVH']
            btw += content['TOTAALBTW']
            tot_incl += content['FACTUURTOTAAL']

        # Total footer
        # ------------
        result += '<tr><td>&nbsp;</td></tr>'
        result += '<tr>'
        result += '<td colspan="3">Totaal ' + str(len(documents)) + ' facturen</td>'
        result += '<td align="right">' + str(tot_excl) + '</td>'
        result += '<td align="right">' + str(btw) + '</td>'
        result += '<td align="right">' + str(tot_incl) + '</td>'
        result += '</tr>'



        # BTW footer
        # ----------
        result += '<tr><td>&nbsp;</td></tr>'
        result += '<tr><td colspan="6"><strong>Per BTW tarief</strong></td></tr>'

        result += '<tr>'
        result += '<td colspan="3">BTW 06.00 %</td>'
        result += '<td align="right">0.00</td>'
        result += '<td align="right">0.00</td>'
        result += '<td align="right">0.00</td>'
        result += '</tr>'

        result += '<tr>'
        result += '<td colspan="3">BTW 12.00 %</td>'
        result += '<td align="right">0.00</td>'
        result += '<td align="right">0.00</td>'
        result += '<td align="right">0.00</td>'
        result += '</tr>'

        result += '<tr>'
        result += '<td colspan="3">BTW 21.00 %</td>'
        result += '<td align="right">' + str(tot_excl) + '</td>'
        result += '<td align="right">' + str(btw) + '</td>'
        result += '<td align="right">' + str(tot_incl) + '</td>'
        result += '</tr>'

        result += '</table></html>'
        return result









    ''' clubit.account.invoice.overview:send()
        --------------------------------------
        This method sends the documents to their partners.
        -------------------------------------------------- '''
    def send(self, cr, uid, ids, context=None):

        assert len(ids) == 1
        now = datetime.datetime.now()
        partner_db = self.pool.get('res.partner')
        overview = self.browse(cr, uid, ids, context=context)[0]
        if not overview.partner_id:
            return {}

        self.write(cr, uid, ids, {'sent_at': now}, context=context)
        ir_model_data = self.pool.get('ir.model.data')
        try:
            compose_form_id = ir_model_data.get_object_reference(cr, uid, 'mail', 'email_compose_message_wizard_form')[1]
        except ValueError:
            compose_form_id = False
        ctx = dict(context)
        ctx.update({
            'default_model': 'clubit.account.invoice.overview',
            'default_res_id': ids[0],
            'default_use_template': False,
            'default_template_id': False,
            'default_composition_mode': 'comment',
            'default_partner_ids': [overview.partner_id.id],
            'default_body': overview.content,
            })
        return {
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'mail.compose.message',
            'views': [(compose_form_id, 'form')],
            'view_id': compose_form_id,
            'target': 'new',
            'context': ctx,
        }













