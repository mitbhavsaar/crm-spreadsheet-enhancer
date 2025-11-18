# -*- coding: utf-8 -*-
{
    'name': "CRM Spreadsheet Enhancement",
    'summary': "Enhances CRM with spreadsheet-based quotation management and product line editing.",
    'author': "Entrivis Tech",
    'website': "https://www.entrivistech.com",
    'category': 'CRM',
    'version': '18.0.1.0.0',
    'depends': [
        'base',
        'crm_customisation',
        'spreadsheet',
        'spreadsheet_edition',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/crm_lead_views.xml',
        'views/res_config_settings_view.xml',
        'views/crm_quatation_template_view.xml',
        'views/crm_quote_spreadsheet_view.xml',
    ],
    'images': ['/static/description/icon.png'],
    'assets': {
        'spreadsheet.o_spreadsheet': [
            'crm_spreadsheet_enhancement/static/src/bundle/**/*.js',
            'crm_spreadsheet_enhancement/static/src/bundle/**/*.xml',
        ],
        'web.assets_backend': [
            'crm_spreadsheet_enhancement/static/src/assets/**/*.js',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': False,
    'auto_install': False,
}
