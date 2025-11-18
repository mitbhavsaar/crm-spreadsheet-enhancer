from odoo import models, fields, api

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'
    
    enable_crm_quotation_templates = fields.Boolean(
        string="CRM Quotation Templates",
    )
    crm_quotation_template_id = fields.Many2one(
        'crm.quotation.template',
        string="Default CRM Quotation Template", 
        related='company_id.crm_quotation_template_id',
        readonly=False,
    )

    def set_values(self):
        res = super().set_values()
        IrConfig = self.env['ir.config_parameter'].sudo()
        IrConfig.set_param('crm_spreadsheet_enhancement.enable_crm_quotation_templates', self.enable_crm_quotation_templates)
        
        # REAL-TIME SYNC - Using config parameters for UI refresh
        if self.enable_crm_quotation_templates and self.crm_quotation_template_id:
            sale_template = self._find_matching_sale_template()
            if sale_template:
                # 🔥 UPDATE CONFIG PARAMETERS - This will reflect in UI
                IrConfig.set_param('sale_management.group_sale_order_template', True)
                IrConfig.set_param('sale.default_sale_order_template_id', sale_template.id)
                
                # Also update company for actual functionality
                self.env.company.sudo().write({
                    'sale_order_template_id': sale_template.id
                })
                
        elif not self.enable_crm_quotation_templates:
            # 🔥 UPDATE CONFIG PARAMETERS
            IrConfig.set_param('sale_management.group_sale_order_template', False)
            IrConfig.set_param('sale.default_sale_order_template_id', '')
            
            # Also update company
            self.env.company.sudo().write({
                'sale_order_template_id': False
            })
        
        return res

    def _find_matching_sale_template(self):
        """Find matching sale.order.template"""
        if not self.crm_quotation_template_id:
            return False
        
        crm_template = self.crm_quotation_template_id
        
        # Search for exact name match
        sale_template = self.env['sale.order.template'].search([
            ('name', '=', crm_template.name)
        ], limit=1)
        
        if not sale_template:
            # Create with same name
            sale_template = self.env['sale.order.template'].create({
                'name': crm_template.name,
                'company_id': self.env.company.id,
            })
        
        return sale_template

    @api.model
    def get_values(self):
        res = super().get_values()
        IrConfig = self.env['ir.config_parameter'].sudo()
        
        # Get CRM settings
        enable_crm = IrConfig.get_param('crm_spreadsheet_enhancement.enable_crm_quotation_templates', False)
        template_id_str = IrConfig.get_param('crm_spreadsheet_enhancement.crm_quotation_template_id', False)
        template_rec = self.env['crm.quotation.template'].browse(int(template_id_str)) if template_id_str and template_id_str.isdigit() else False
        
        # Get Sales settings from config parameters for UI
        sales_enabled = IrConfig.get_param('sale_management.group_sale_order_template', False)
        sales_template_id = IrConfig.get_param('sale.default_sale_order_template_id', False)
        sales_template = self.env['sale.order.template'].browse(int(sales_template_id)) if sales_template_id and sales_template_id.isdigit() else False
        
        res.update({
            'enable_crm_quotation_templates': enable_crm,
            'crm_quotation_template_id': template_rec,

        })
        return res