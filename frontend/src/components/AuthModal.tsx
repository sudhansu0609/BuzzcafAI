import React, { useState, useEffect } from 'react';
import { Lock, Key, ShieldCheck, LogOut, Eye, EyeOff, X, AlertCircle, UserPlus, UserCheck, Users } from 'lucide-react';
import { loginUser, registerUser, setPassword, toggleAuth, logoutUser, fetchServerUsers } from '../services/api';
import { UserService, UserProfile } from '../services/UserService';

interface AuthModalProps {
  mode: 'login' | 'settings';
  authStatus: { authEnabled: boolean; hasGlobalPassword?: boolean; isAuthenticated: boolean };
  onSuccess: () => void;
  onClose?: () => void;
}

export const AuthModal: React.FC<AuthModalProps> = ({ mode, authStatus, onSuccess, onClose }) => {
  const [activeSubTab, setActiveSubTab] = useState<'signin' | 'signup'>('signin');
  
  // User list
  const [userProfiles, setUserProfiles] = useState<UserProfile[]>(UserService.getAllUsers());
  const [selectedUserId, setSelectedUserId] = useState<string>(UserService.getActiveUser().id);

  // Signin form state
  const [loginPassword, setLoginPassword] = useState('');
  const [showLoginPassword, setShowLoginPassword] = useState(false);
  const [loginErr, setLoginErr] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Signup form state
  const [regName, setRegName] = useState('');
  const [regRole, setRegRole] = useState('');
  const [regAvatarIcon, setRegAvatarIcon] = useState('👤');
  const [regPassword, setRegPassword] = useState('');

  // Settings form state
  const [authEnabledState, setAuthEnabledState] = useState(authStatus.authEnabled);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPasswords, setShowPasswords] = useState(false);
  const [settingsMsg, setSettingsMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const AVATAR_ICONS = ['👑', '👤', '🎬', '🚀', '🎨', '💼', '🎧', '🔬'];

  useEffect(() => {
    fetchServerUsers().then((serverUsers) => {
      if (serverUsers && serverUsers.length > 0) {
        UserService.syncWithServer(serverUsers);
        setUserProfiles(UserService.getAllUsers());
      }
    }).catch(() => {});
  }, []);

  const handleLoginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setLoginErr(null);

    try {
      const res = await loginUser(selectedUserId, loginPassword);
      if (res.user) {
        UserService.setActiveUser(res.user);
      } else {
        const found = userProfiles.find(u => u.id === selectedUserId);
        if (found) UserService.setActiveUser(found);
      }
      onSuccess();
    } catch (err: any) {
      setLoginErr(err.message || 'Login failed. Please check your password.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRegisterSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!regName.trim()) {
      setLoginErr('Please enter a workspace name');
      return;
    }

    setIsSubmitting(true);
    setLoginErr(null);

    try {
      const res = await registerUser(regName, regRole, regAvatarIcon, regPassword);
      const newUser = res.user || UserService.createNewUser(regName, regRole, regAvatarIcon, res.user?.id);
      UserService.setActiveUser(newUser);
      onSuccess();
    } catch (err: any) {
      setLoginErr(err.message || 'Failed to create new user account.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    setSettingsMsg(null);

    if (newPassword) {
      if (newPassword.length < 3) {
        setSettingsMsg({ type: 'error', text: 'Password must be at least 3 characters long.' });
        return;
      }
      if (newPassword !== confirmPassword) {
        setSettingsMsg({ type: 'error', text: 'New passwords do not match.' });
        return;
      }
    }

    setIsSubmitting(true);

    try {
      if (newPassword) {
        await setPassword(newPassword, currentPassword || undefined, authEnabledState);
        setSettingsMsg({ type: 'success', text: 'Password updated successfully!' });
      } else {
        await toggleAuth(authEnabledState);
        setSettingsMsg({ type: 'success', text: `Password protection ${authEnabledState ? 'enabled' : 'disabled'}` });
      }
      onSuccess();
      setTimeout(() => {
        if (onClose) onClose();
      }, 1200);
    } catch (err: any) {
      setSettingsMsg({ type: 'error', text: err.message || 'Failed to update security settings.' });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleLogout = async () => {
    await logoutUser();
    onSuccess();
    if (onClose) onClose();
  };

  if (mode === 'login') {
    return (
      <div style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        background: 'rgba(15, 23, 42, 0.85)',
        backdropFilter: 'blur(12px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px'
      }}>
        <div style={{
          background: '#ffffff',
          width: '100%',
          maxWidth: '460px',
          borderRadius: '24px',
          padding: '32px',
          boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.35)',
          border: '1px solid #cbd5e1',
          position: 'relative'
        }}>
          {/* Top Logo */}
          <div style={{
            width: '60px',
            height: '60px',
            borderRadius: '16px',
            background: 'linear-gradient(135deg, #0f172a 0%, #334155 100%)',
            margin: '0 auto 16px auto',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 8px 20px rgba(15, 23, 42, 0.25)'
          }}>
            <Lock size={30} color="#ffffff" />
          </div>

          <h2 style={{ fontSize: '22px', fontWeight: 800, color: '#0f172a', marginBottom: '6px', textAlign: 'center' }}>
            MidnightBuzz User Workspace
          </h2>
          <p style={{ fontSize: '13px', color: '#475569', marginBottom: '20px', lineHeight: 1.5, textAlign: 'center' }}>
            Sign in to access your private AI agents & isolated chat history
          </p>

          {/* Sub Tabs: Sign In / Create Account */}
          <div style={{
            display: 'flex',
            background: '#f1f5f9',
            padding: '4px',
            borderRadius: '12px',
            marginBottom: '20px'
          }}>
            <button
              type="button"
              onClick={() => { setActiveSubTab('signin'); setLoginErr(null); }}
              style={{
                flex: 1,
                padding: '8px 12px',
                borderRadius: '8px',
                border: 'none',
                background: activeSubTab === 'signin' ? '#ffffff' : 'transparent',
                color: activeSubTab === 'signin' ? '#0f172a' : '#64748b',
                fontWeight: 700,
                fontSize: '13px',
                cursor: 'pointer',
                boxShadow: activeSubTab === 'signin' ? '0 2px 6px rgba(0,0,0,0.08)' : 'none',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px'
              }}
            >
              <UserCheck size={16} /> Sign In Existing User
            </button>
            <button
              type="button"
              onClick={() => { setActiveSubTab('signup'); setLoginErr(null); }}
              style={{
                flex: 1,
                padding: '8px 12px',
                borderRadius: '8px',
                border: 'none',
                background: activeSubTab === 'signup' ? '#ffffff' : 'transparent',
                color: activeSubTab === 'signup' ? '#0f172a' : '#64748b',
                fontWeight: 700,
                fontSize: '13px',
                cursor: 'pointer',
                boxShadow: activeSubTab === 'signup' ? '0 2px 6px rgba(0,0,0,0.08)' : 'none',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px'
              }}
            >
              <UserPlus size={16} /> Create New Account
            </button>
          </div>

          {activeSubTab === 'signin' ? (
            <form onSubmit={handleLoginSubmit}>
              {/* Account Selection */}
              <div style={{ marginBottom: '16px', textAlign: 'left' }}>
                <label style={{ fontSize: '12px', fontWeight: 700, color: '#334155', display: 'block', marginBottom: '6px' }}>
                  Select User Account
                </label>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '180px', overflowY: 'auto' }}>
                  {userProfiles.map((user) => {
                    const isSelected = selectedUserId === user.id;
                    return (
                      <div
                        key={user.id}
                        onClick={() => setSelectedUserId(user.id)}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          padding: '10px 14px',
                          borderRadius: '12px',
                          border: isSelected ? '2px solid #6366f1' : '1px solid #e2e8f0',
                          background: isSelected ? '#f8fafc' : '#ffffff',
                          cursor: 'pointer'
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <span style={{ fontSize: '18px' }}>{user.avatarIcon || '👤'}</span>
                          <div>
                            <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a' }}>{user.name}</div>
                            <div style={{ fontSize: '11px', color: '#64748b' }}>{user.role}</div>
                          </div>
                        </div>
                        {user.hasPassword && <Lock size={14} color="#94a3b8" />}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Password Field */}
              <div style={{ position: 'relative', marginBottom: '16px', textAlign: 'left' }}>
                <label style={{ fontSize: '12px', fontWeight: 700, color: '#334155', display: 'block', marginBottom: '6px' }}>
                  Password
                </label>
                <div style={{ position: 'relative' }}>
                  <input
                    type={showLoginPassword ? 'text' : 'password'}
                    value={loginPassword}
                    onChange={(e) => setLoginPassword(e.target.value)}
                    placeholder="Enter password (leave empty if not set)..."
                    style={{
                      width: '100%',
                      padding: '12px 42px 12px 14px',
                      borderRadius: '10px',
                      border: loginErr ? '1.5px solid #ef4444' : '1px solid #cbd5e1',
                      fontSize: '13px',
                      color: '#0f172a',
                      outline: 'none'
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => setShowLoginPassword(!showLoginPassword)}
                    style={{
                      position: 'absolute',
                      right: '12px',
                      top: '50%',
                      transform: 'translateY(-50%)',
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      color: '#64748b'
                    }}
                  >
                    {showLoginPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                  </button>
                </div>
              </div>

              {loginErr && (
                <div style={{
                  background: 'rgba(239, 68, 68, 0.1)',
                  border: '1px solid #f87171',
                  color: '#dc2626',
                  padding: '8px 12px',
                  borderRadius: '8px',
                  fontSize: '12px',
                  marginBottom: '16px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  textAlign: 'left'
                }}>
                  <AlertCircle size={16} /> {loginErr}
                </div>
              )}

              <button
                type="submit"
                disabled={isSubmitting}
                style={{
                  width: '100%',
                  background: '#0f172a',
                  color: '#ffffff',
                  padding: '14px',
                  borderRadius: '12px',
                  fontSize: '14px',
                  fontWeight: 700,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '8px',
                  boxShadow: '0 4px 14px rgba(15, 23, 42, 0.2)',
                  border: 'none'
                }}
              >
                <Key size={18} /> {isSubmitting ? 'Logging in...' : 'Sign In to Workspace'}
              </button>
            </form>
          ) : (
            <form onSubmit={handleRegisterSubmit} style={{ textAlign: 'left', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b', display: 'block', marginBottom: '4px' }}>Choose Avatar Icon</label>
                <div style={{ display: 'flex', gap: '8px', overflowX: 'auto' }}>
                  {AVATAR_ICONS.map((icon) => (
                    <button
                      type="button"
                      key={icon}
                      onClick={() => setRegAvatarIcon(icon)}
                      style={{
                        background: regAvatarIcon === icon ? '#e0e7ff' : '#ffffff',
                        border: regAvatarIcon === icon ? '2px solid #6366f1' : '1px solid #cbd5e1',
                        borderRadius: '10px',
                        padding: '6px 10px',
                        fontSize: '18px',
                        cursor: 'pointer'
                      }}
                    >
                      {icon}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b', display: 'block', marginBottom: '4px' }}>User / Workspace Name</label>
                <input
                  type="text"
                  placeholder="e.g. Rahul Workspace"
                  value={regName}
                  onChange={(e) => setRegName(e.target.value)}
                  style={{ width: '100%', padding: '10px', borderRadius: '10px', border: '1px solid #cbd5e1', fontSize: '13px' }}
                  required
                />
              </div>

              <div>
                <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b', display: 'block', marginBottom: '4px' }}>Role / Description</label>
                <input
                  type="text"
                  placeholder="e.g. Content Creator"
                  value={regRole}
                  onChange={(e) => setRegRole(e.target.value)}
                  style={{ width: '100%', padding: '10px', borderRadius: '10px', border: '1px solid #cbd5e1', fontSize: '13px' }}
                />
              </div>

              <div>
                <label style={{ fontSize: '11px', fontWeight: 600, color: '#64748b', display: 'block', marginBottom: '4px' }}>Set Password (Optional)</label>
                <input
                  type="password"
                  placeholder="Set optional password..."
                  value={regPassword}
                  onChange={(e) => setRegPassword(e.target.value)}
                  style={{ width: '100%', padding: '10px', borderRadius: '10px', border: '1px solid #cbd5e1', fontSize: '13px' }}
                />
              </div>

              {loginErr && (
                <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', color: '#dc2626', padding: '8px 12px', borderRadius: '8px', fontSize: '12px' }}>
                  {loginErr}
                </div>
              )}

              <button
                type="submit"
                disabled={isSubmitting || !regName.trim()}
                style={{
                  width: '100%',
                  background: '#6366f1',
                  color: '#ffffff',
                  padding: '12px',
                  borderRadius: '12px',
                  fontSize: '13px',
                  fontWeight: 700,
                  cursor: isSubmitting ? 'not-allowed' : 'pointer',
                  border: 'none',
                  marginTop: '6px'
                }}
              >
                {isSubmitting ? 'Creating Account...' : 'Register & Enter Workspace'}
              </button>
            </form>
          )}
        </div>
      </div>
    );
  }

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      zIndex: 9999,
      background: 'rgba(15, 23, 42, 0.65)',
      backdropFilter: 'blur(8px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '20px'
    }}>
      <div style={{
        background: '#ffffff',
        width: '100%',
        maxWidth: '460px',
        borderRadius: '20px',
        padding: '28px',
        boxShadow: '0 20px 40px rgba(0, 0, 0, 0.2)',
        border: '1px solid #cbd5e1',
        position: 'relative'
      }}>
        {onClose && (
          <button
            onClick={onClose}
            style={{
              position: 'absolute',
              top: '18px',
              right: '18px',
              background: '#f1f5f9',
              border: 'none',
              width: '32px',
              height: '32px',
              borderRadius: '50%',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#475569'
            }}
          >
            <X size={18} />
          </button>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px' }}>
          <div style={{
            width: '44px',
            height: '44px',
            borderRadius: '12px',
            background: '#0f172a',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}>
            <ShieldCheck size={24} color="#ffffff" />
          </div>
          <div>
            <h3 style={{ fontSize: '18px', fontWeight: 800, color: '#0f172a' }}>Security & Password Lock</h3>
            <p style={{ fontSize: '12px', color: '#475569' }}>Configure password protection for MidnightBuzz</p>
          </div>
        </div>

        <form onSubmit={handleSaveSettings} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Toggle Password Protection */}
          <div style={{
            background: '#f8fafc',
            padding: '14px',
            borderRadius: '12px',
            border: '1px solid #e2e8f0',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between'
          }}>
            <div>
              <div style={{ fontSize: '13px', fontWeight: 700, color: '#0f172a' }}>Password Protection</div>
              <div style={{ fontSize: '11px', color: '#64748b' }}>Require login password to access site</div>
            </div>
            <label style={{ position: 'relative', display: 'inline-block', width: '44px', height: '24px', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={authEnabledState}
                onChange={(e) => setAuthEnabledState(e.target.checked)}
                style={{ opacity: 0, width: 0, height: 0 }}
              />
              <span style={{
                position: 'absolute',
                inset: 0,
                backgroundColor: authEnabledState ? '#0f172a' : '#cbd5e1',
                borderRadius: '24px',
                transition: '0.3s'
              }}>
                <span style={{
                  position: 'absolute',
                  content: '""',
                  height: '18px',
                  width: '18px',
                  left: authEnabledState ? '22px' : '3px',
                  bottom: '3px',
                  backgroundColor: '#ffffff',
                  borderRadius: '50%',
                  transition: '0.3s'
                }} />
              </span>
            </label>
          </div>

          {/* Password Fields */}
          {(authEnabledState || authStatus.hasGlobalPassword) && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', background: '#f8fafc', padding: '14px', borderRadius: '12px', border: '1px solid #e2e8f0' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '12px', fontWeight: 700, color: '#0f172a' }}>
                  {authStatus.hasGlobalPassword ? 'Change Master Password' : 'Set New Access Password'}
                </span>
                <button
                  type="button"
                  onClick={() => setShowPasswords(!showPasswords)}
                  style={{ background: 'none', border: 'none', fontSize: '11px', color: '#3b82f6', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px' }}
                >
                  {showPasswords ? <EyeOff size={14} /> : <Eye size={14} />} {showPasswords ? 'Hide' : 'Show'}
                </button>
              </div>

              {authStatus.hasGlobalPassword && (
                <div>
                  <label style={{ fontSize: '11px', color: '#64748b', display: 'block', marginBottom: '4px' }}>Current Password</label>
                  <input
                    type={showPasswords ? 'text' : 'password'}
                    value={currentPassword}
                    onChange={(e) => setCurrentPassword(e.target.value)}
                    placeholder="Enter current password..."
                    style={{ width: '100%', padding: '8px 12px', fontSize: '13px', borderRadius: '8px', border: '1px solid #cbd5e1' }}
                  />
                </div>
              )}

              <div>
                <label style={{ fontSize: '11px', color: '#64748b', display: 'block', marginBottom: '4px' }}>New Password</label>
                <input
                  type={showPasswords ? 'text' : 'password'}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Enter new password..."
                  style={{ width: '100%', padding: '8px 12px', fontSize: '13px', borderRadius: '8px', border: '1px solid #cbd5e1' }}
                />
              </div>

              <div>
                <label style={{ fontSize: '11px', color: '#64748b', display: 'block', marginBottom: '4px' }}>Confirm New Password</label>
                <input
                  type={showPasswords ? 'text' : 'password'}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Re-enter new password..."
                  style={{ width: '100%', padding: '8px 12px', fontSize: '13px', borderRadius: '8px', border: '1px solid #cbd5e1' }}
                />
              </div>
            </div>
          )}

          {settingsMsg && (
            <div style={{
              background: settingsMsg.type === 'error' ? 'rgba(239, 68, 68, 0.1)' : 'rgba(16, 185, 129, 0.1)',
              border: settingsMsg.type === 'error' ? '1px solid #f87171' : '1px solid #34d399',
              color: settingsMsg.type === 'error' ? '#dc2626' : '#15803d',
              padding: '10px',
              borderRadius: '8px',
              fontSize: '12px',
              fontWeight: 600
            }}>
              {settingsMsg.text}
            </div>
          )}

          <div style={{ display: 'flex', gap: '10px', marginTop: '6px' }}>
            {authStatus.isAuthenticated && authStatus.authEnabled && (
              <button
                type="button"
                onClick={handleLogout}
                style={{
                  background: '#f1f5f9',
                  color: '#dc2626',
                  border: '1px solid #f87171',
                  padding: '10px 14px',
                  borderRadius: '10px',
                  fontSize: '12px',
                  fontWeight: 700,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px'
                }}
              >
                <LogOut size={16} /> Log Out
              </button>
            )}

            <button
              type="submit"
              disabled={isSubmitting}
              style={{
                flex: 1,
                background: '#0f172a',
                color: '#ffffff',
                padding: '10px 16px',
                borderRadius: '10px',
                fontSize: '13px',
                fontWeight: 700,
                cursor: 'pointer',
                border: 'none'
              }}
            >
              {isSubmitting ? 'Saving...' : 'Save Security Settings'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

