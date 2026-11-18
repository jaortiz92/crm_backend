# Especificación Backend — Planeación Tributaria del Presupuesto 2027

## 1. Contexto y objetivo

El módulo presupuestal debe permitir simular el impacto tributario de una empresa colombiana dentro de un escenario de presupuesto. La simulación debe comparar:

- Régimen ordinario.
- Régimen SIMPLE.

El resultado debe reflejar simultáneamente:

- Impuesto causado.
- Anticipos y retenciones.
- Obligaciones periódicas.
- Fechas de declaración.
- Fechas de pago.
- Impacto en utilidad.
- Impacto en flujo de caja.

La implementación es presupuestal y estimativa. No reemplaza una declaración tributaria ni el criterio del contador o asesor fiscal.

## 2. Alcance tributario

### Incluido

1. Impuesto de renta para régimen ordinario.
2. Impuesto SIMPLE.
3. ReteIVA.
4. Retención en la fuente.
5. ICA.
6. ReteICA.
7. Calendario tributario configurable por año y régimen.
8. Comparación entre escenarios tributarios.

### Fuera de alcance inicial

- Reimplementación del IVA existente.
- Presentación electrónica ante DIAN o municipios.
- Generación de formularios oficiales.
- Consulta automática de tarifas en servicios externos.
- Impuesto al consumo, patrimonio, GMF y aranceles como módulos de cálculo independientes. Podrán incorporarse posteriormente.

## 3. Terminología

- **Régimen ordinario:** impuesto de renta calculado sobre una renta líquida fiscal estimada.
- **Régimen SIMPLE:** impuesto calculado sobre ingresos brutos según actividad, grupo, rango y parámetros configurados.
- **Impuesto causado:** obligación correspondiente al periodo fiscal.
- **Anticipo:** pago realizado antes de la liquidación definitiva.
- **Retención sufrida:** valor retenido a la empresa y potencialmente descontable.
- **Retención practicada:** valor retenido por la empresa a terceros y pendiente de declarar/pagar.
- **Calendario tributario:** periodos, vencimientos, declaraciones y pagos de una obligación.

## 4. Modelo de datos propuesto

### 4.1. tax_profiles

Perfil tributario configurable para una empresa y periodo.

Campos mínimos:

- `id_tax_profile`
- `profile_name`
- `tax_year`
- `regime`: `ordinary` | `simple`
- `id_company` o referencia equivalente, si existe catálogo de empresa
- `main_municipality_code`
- `economic_activity_code`
- `iva_responsible`
- `withholding_agent`
- `reteiva_agent`
- `reteica_agent`
- `status`: `draft` | `active` | `archived`
- `created_at`
- `updated_at`

Regla: debe existir como máximo un perfil activo por empresa, año y régimen.

### 4.2. tax_rates

Parámetros y tarifas vigentes.

Campos mínimos:

- `id_tax_rate`
- `tax_type`: `income_ordinary`, `simple`, `reteiva`, `withholding`, `ica`, `reteica`
- `tax_year`
- `regime`, nullable cuando no aplique
- `economic_activity_code`, nullable
- `municipality_code`, nullable
- `income_min`, nullable
- `income_max`, nullable
- `rate`
- `fixed_amount`, nullable
- `base_type`: `net_income`, `gross_income`, `iva_amount`, `payment_base`, `fiscal_income`
- `valid_from`
- `valid_to`
- `is_active`
- `source_note`

No se deben codificar tarifas tributarias directamente en Python.

### 4.3. tax_calendar_periods

Calendario de obligaciones tributarias.

Campos mínimos:

- `id_tax_calendar_period`
- `tax_year`
- `regime`, nullable
- `tax_type`
- `period_code`: mensual, bimestral, cuatrimestral, anual u otro código configurable
- `period_start`
- `period_end`
- `declaration_due_date`
- `payment_due_date`
- `payment_year`
- `sequence`
- `is_active`
- `notes`

El año de pago debe poder ser diferente al año causado. Esto es obligatorio para renta ordinaria.

### 4.4. budget_tax_assumptions

Supuestos específicos de un escenario presupuestal.

Campos mínimos:

- `id_budget_tax_assumption`
- `id_budget`
- `id_tax_profile`
- `taxable_income_adjustments`
- `non_deductible_expenses`
- `exempt_income`
- `tax_losses`
- `tax_discounts`
- `prior_advances`
- `prior_withholdings`
- `monthly_sales_taxable_base`, si se requiere override
- `notes`
- `created_at`
- `updated_at`

Los valores deben manejarse con precisión decimal y no con `float`.

### 4.5. budget_tax_results

Resultado calculado y trazable para un presupuesto.

Campos mínimos:

- `id_budget_tax_result`
- `id_budget`
- `id_budget_tax_assumption`
- `tax_type`
- `period_start`
- `period_end`
- `taxable_base`
- `tax_rate`
- `tax_caused`
- `advance_amount`
- `withholding_amount`
- `balance_payable`
- `declaration_date`
- `payment_date`
- `payment_year`
- `calculation_trace` en JSON
- `warnings` en JSON
- `calculated_at`

Se recomienda calcular bajo demanda y persistir el snapshot únicamente cuando el negocio necesite historial o auditoría.

## 5. Reglas de cálculo

### 5.1. Régimen ordinario

La base será configurable y deberá partir de los resultados presupuestados:

```text
Resultado contable antes de impuestos
+ gastos no deducibles
- ingresos no gravados o exentos
+/- diferencias fiscales
- pérdidas fiscales compensables
- descuentos o beneficios aplicables
= renta líquida fiscal estimada
```

Luego:

```text
renta líquida fiscal × tarifa ordinaria
= impuesto de renta causado
```

El pago presupuestal se programará en el año siguiente, según `tax_calendar_periods`. Las retenciones y anticipos reducen el saldo a pagar, pero no el impuesto causado.

### 5.2. Régimen SIMPLE

La base se calculará sobre ingresos brutos según los parámetros vigentes:

```text
ingresos brutos del periodo × tarifa SIMPLE
= impuesto SIMPLE del periodo
```

La tarifa debe resolverse por actividad, grupo, rango de ingresos y demás parámetros configurados. El calendario debe distribuir anticipos durante el mismo año fiscal.

### 5.3. ReteIVA

El IVA existente será la fuente de IVA generado y descontable. El nuevo motor no debe duplicar su cálculo.

```text
IVA de la operación × porcentaje de reteIVA
= reteIVA
```

Debe separar:

- IVA generado.
- IVA descontable.
- ReteIVA practicado.
- ReteIVA sufrido.
- Saldo por declarar/pagar.
- Fecha de declaración y pago.

ReteIVA es flujo/saldo tributario, no gasto automático.

### 5.4. Retención en la fuente

Para cada base sujeta a retención:

```text
base de retención × tarifa configurada
= retención
```

Debe diferenciar retenciones practicadas a terceros y retenciones sufridas por la empresa.

### 5.5. ICA y reteICA

ICA:

```text
base gravable municipal × tarifa ICA
= ICA causado
```

ReteICA:

```text
base sujeta × tarifa reteICA
= reteICA
```

La tarifa debe resolver municipio, actividad, año y vigencia.

### 5.6. Impacto contable y de caja

Cada resultado debe identificar si corresponde a:

- Gasto o impuesto causado.
- Saldo tributario.
- Anticipo.
- Retención.
- Salida de caja.

No se debe sumar automáticamente una retención como gasto.

## 6. Calendario por régimen

### Régimen SIMPLE

- Anticipos durante el año fiscal.
- Periodicidad configurable.
- Declaración y pago según cada periodo.
- Ajuste o saldo final si corresponde.

### Régimen ordinario

- Impuesto causado al cierre del año presupuestado.
- Anticipos y retenciones descontables.
- Declaración en el año siguiente.
- Pago programado en el año siguiente.

El motor debe permitir que `tax_year` y `payment_year` sean diferentes.

## 7. API propuesta

Rutas bajo `/budget/tax`:

- `GET /profiles?tax_year=`
- `POST /profiles`
- `PUT /profiles/{id}`
- `GET /rates?tax_year=&tax_type=`
- `POST /rates`
- `PUT /rates/{id}`
- `GET /calendar?tax_year=&regime=`
- `POST /calendar`
- `PUT /calendar/{id}`
- `GET /budgets/{id_budget}/assumptions`
- `PUT /budgets/{id_budget}/assumptions`
- `POST /budgets/{id_budget}/calculate`
- `GET /budgets/{id_budget}/summary`
- `GET /budgets/{id_budget}/comparison?regime_a=&regime_b=`
- `GET /budgets/{id_budget}/cash-flow`

La respuesta de cálculo debe incluir los supuestos, advertencias, trazabilidad y resultados por periodo.

## 8. Seguridad y permisos

- Consulta: roles financieros autorizados.
- Edición de tarifas y calendarios: administración financiera.
- Activación de un perfil tributario: gerente/administrador.
- Todas las restricciones deben validarse en backend, no únicamente en frontend.

## 9. Precisión y validaciones

- Usar `Decimal`/`Numeric` para dinero y porcentajes.
- Rechazar tarifas negativas o superiores al rango permitido.
- Rechazar periodos solapados para la misma combinación de impuesto, año, régimen, municipio y actividad.
- Generar advertencia cuando falte tarifa, calendario o perfil.
- No asumir cero ante configuración faltante.
- Mantener todos los cálculos reproducibles mediante `calculation_trace`.

## 10. Criterios de aceptación

1. Se puede calcular un presupuesto con régimen ordinario.
2. Se puede calcular un presupuesto con régimen SIMPLE.
3. El régimen SIMPLE genera anticipos durante el mismo año.
4. El régimen ordinario genera impuesto causado en el año vigente y pago en el siguiente.
5. ReteIVA utiliza el IVA existente sin duplicarlo.
6. Se calculan retención en la fuente, ICA y reteICA.
7. Las tarifas y fechas no están hardcodeadas.
8. Se puede comparar el total anual y el flujo mensual de ambos regímenes.
9. Las retenciones no se registran automáticamente como gasto.
10. La ausencia de parámetros produce advertencias explícitas.
11. Los cálculos utilizan precisión decimal.
12. Existen pruebas para escenarios sin utilidad, con pérdidas, sin calendario y con pago en año siguiente.

## 11. Dependencias y advertencias

- Validación de fórmulas, tarifas y calendario por contador/asesor tributario.
- Confirmación del régimen real de la compañía.
- Confirmación de actividad económica y municipios.
- Migraciones manuales o controladas para el esquema existente, dado que `create_all` no altera tablas existentes.

## Enmienda — Régimen SIMPLE por bimestre

La tarifa del régimen SIMPLE **no es una tarifa anual única**. El cálculo debe ejecutarse de forma independiente para cada periodo bimestral configurado.

Para cada bimestre:

```text
ingresos del bimestre
→ búsqueda del rango aplicable
→ tarifa correspondiente al rango
→ impuesto causado del bimestre
→ anticipo, retenciones y saldo
→ fecha de declaración y pago
```

Reglas obligatorias:

- La base es el ingreso del bimestre, no el total anual.
- La tarifa se resuelve nuevamente en cada bimestre.
- Un bimestre puede utilizar una tarifa diferente a otro.
- La respuesta de la API debe incluir el detalle por periodo: ingresos, rango, tarifa, impuesto causado, anticipos, retenciones, saldo y fechas.
- El resumen anual debe ser la suma de los resultados bimestrales, no el resultado de aplicar una tarifa promedio o única.
- El frontend no debe solicitar ni permitir una tarifa SIMPLE anual única.
