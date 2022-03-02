from odoo import api, fields, models, _


class REsCompany(models.Model):
    _inherit = 'res.company'

    bank = fields.Char('Bank')
    branch = fields.Char('Branch Number')
    current_account = fields.Char('Current Account')
