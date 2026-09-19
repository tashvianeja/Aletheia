/* Minimal validator for the generated Pydantic JSON Schema vocabulary. */
(() => {
  function validate(value, schema, root = schema) {
    if (schema.$ref) {
      const target = schema.$ref.replace(/^#\//, '').split('/').reduce((node, key) => node[key], root);
      return validate(value, target, root);
    }
    if (schema.anyOf) return schema.anyOf.some(option => validate(value, option, root));
    if (schema.oneOf) return schema.oneOf.filter(option => validate(value, option, root)).length === 1;
    if ('const' in schema && value !== schema.const) return false;
    if (schema.enum && !schema.enum.includes(value)) return false;
    if (schema.type === 'null') return value === null;
    if (schema.type === 'object') {
      if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
      if ((schema.required || []).some(key => !(key in value))) return false;
      if (schema.additionalProperties === false && Object.keys(value).some(key => !schema.properties?.[key])) return false;
      return Object.entries(schema.properties || {}).every(([key, child]) => !(key in value) || validate(value[key], child, root));
    }
    if (schema.type === 'array') return Array.isArray(value) && value.every(item => validate(item, schema.items || {}, root));
    if (schema.type === 'string') return typeof value === 'string' && (!schema.minLength || value.length >= schema.minLength) && (!schema.maxLength || value.length <= schema.maxLength);
    if (schema.type === 'boolean') return typeof value === 'boolean';
    if (schema.type === 'integer' || schema.type === 'number') return typeof value === 'number' && Number.isFinite(value) && (schema.type !== 'integer' || Number.isInteger(value)) && (schema.minimum === undefined || value >= schema.minimum) && (schema.maximum === undefined || value <= schema.maximum);
    return true;
  }
  globalThis.PGValidate = validate;
})();
