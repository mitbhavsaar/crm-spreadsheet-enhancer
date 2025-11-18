# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class CrmQuotationTemplate(models.Model):
    _name = 'crm.quotation.template'
    _description = 'CRM Quotation Template'
    _order = 'name'

    # -----------------------------
    # BASIC INFO
    # -----------------------------
    name = fields.Char(string="Template Name", required=True)
    description = fields.Text(string="Description")
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company',
        string="Company",
        default=lambda self: self.env.company
    )
    quote_validity = fields.Integer(string="Quotation Validity (days)", default=30)
    confirmation_mail = fields.Boolean(string="Confirmation Mail")
    online_signature = fields.Boolean(string="Online Signature", default=True)
    online_payment = fields.Boolean(string="Online Payment", default=True)
    payment_percentage = fields.Float(string="Payment (%)", default=100)
    invoicing_journal_id = fields.Many2one('account.journal', string="Invoicing Journal")
    quote_calculator_id = fields.Many2one(
    'crm.lead.spreadsheet',
    string="Quote Calculator",
    )

    # -----------------------------
    # ONE2MANY MATERIAL LINES
    # -----------------------------
    line_ids = fields.One2many(
        'crm.quotation.template.line',
        'template_id',
        string='Material Lines',
        copy=True
    )


class CrmQuotationTemplateLine(models.Model):
    _name = 'crm.quotation.template.line'
    _description = 'CRM Quotation Template Line'
    _order = 'template_id, sequence, id'

    # -----------------------------
    # BASIC FIELDS
    # -----------------------------
    template_id = fields.Many2one(
        'crm.quotation.template',
        string='Quotation Template',
        ondelete='cascade',
        required=True
    )
    sequence = fields.Integer(default=10)
    
    