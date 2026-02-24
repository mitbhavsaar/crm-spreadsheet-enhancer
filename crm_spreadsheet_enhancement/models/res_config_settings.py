from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    enable_crm_quotation_templates = fields.Boolean(
        string="CRM Quotation Templates",
        config_parameter='crm_spreadsheet_enhancement.enable_crm_quotation_templates'
        
    )

    crm_quotation_template_id = fields.Many2one(
        'crm.quotation.template',
        string="Default CRM Quotation Template",
        config_parameter='crm_spreadsheet_enhancement.crm_quotation_template_id'


    )

    def set_values(self):
        super().set_values()
        config = self.env['ir.config_parameter'].sudo()
        config.set_param(
            'crm_spreadsheet_enhancement.enable_crm_quotation_templates',
            self.enable_crm_quotation_templates
        )
        config.set_param(
            'crm_spreadsheet_enhancement.crm_quotation_template_id',
            self.crm_quotation_template_id.id or ''
        )

    @api.model
    def get_values(self):
        res = super().get_values()
        config = self.env['ir.config_parameter'].sudo()

        enable = config.get_param(
            'crm_spreadsheet_enhancement.enable_crm_quotation_templates', 'False'
        )

        template_id = config.get_param(
            'crm_spreadsheet_enhancement.crm_quotation_template_id'
        )

        res.update({
            'enable_crm_quotation_templates': enable == 'True',
            'crm_quotation_template_id': int(template_id) if template_id else False,
        })
        return res
