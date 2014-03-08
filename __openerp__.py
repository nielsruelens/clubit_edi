{
    'name': 'clubit_edi',
    'version': '1.0',
    'category': 'Warehouse',
    'description': "Custom EDI Implementation",
    'author': 'Niels Ruelens',
    'website': 'http://clubit.be',
    'summary': 'Custom EDI Implementation',
    'sequence': 9,
    'depends': [
        'stock',
        'sale',
        'account',
        'edi',
        'clubit_tools',
        'clubit_product',
        'clubit_reference_chainer',
        'delivery',
    ],
    'data': [
        'stock_view.xml',
        'account_view.xml',
        'invoice_overview.xml',
        'config.xml',
        'wizard/clubit_tools_edi_wizard_outgoing_delivery.xml',
        'wizard/clubit_tools_edi_wizard_outgoing_desadv.xml',
        'wizard/clubit_tools_edi_wizard_outgoing_invoice.xml',
    ],
    'demo': [
    ],
    'test': [
    ],
    'css': [
    ],
    'images': [
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}