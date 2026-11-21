export default function Button({ variant = 'primary', icon: Icon, children, className = '', ...props }) {
  return (
    <button type="button" className={`btn btn-${variant} ${className}`} {...props}>
      {Icon && <Icon size={18} aria-hidden="true" />}
      {children}
    </button>
  )
}
